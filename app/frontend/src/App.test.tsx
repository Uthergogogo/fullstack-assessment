import '@testing-library/jest-dom/vitest'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { Cart, Product, Sku } from './api'

function sku(color: string, size: string, price: number, stock: number, available = true): Sku {
  return {
    id: `mug-${color}-${size}`,
    option_values: { color, size },
    price_minor: price,
    available_quantity: stock,
    is_available: available,
    image_url: `/images/${color}-${size}.webp`,
  }
}

const product: Product = {
  id: 'silt-mug',
  name: 'Silt Stoneware Mug',
  description: 'A softly rounded ceramic mug.',
  currency: 'AUD',
  options: [
    { id: 'color', label: 'Glaze', values: [
      { id: 'oat', label: 'Oat' }, { id: 'moss', label: 'Moss' }, { id: 'ink', label: 'Ink' },
    ] },
    { id: 'size', label: 'Capacity', values: [
      { id: '250', label: '250 mL' }, { id: '350', label: '350 mL' }, { id: '450', label: '450 mL' },
    ] },
  ],
  skus: [
    sku('oat', '250', 2400, 8), sku('oat', '350', 2800, 12), sku('oat', '450', 3200, 4),
    sku('moss', '250', 2500, 6), sku('moss', '350', 2900, 1), sku('moss', '450', 3300, 0, false),
    sku('ink', '250', 2500, 0), sku('ink', '350', 2900, 5),
  ],
}

function cart(count = 0, skuId = 'mug-oat-250'): Cart {
  return {
    items: count ? [{ sku_id: skuId, quantity: count, unit_price_minor: 2400, currency: 'AUD' }] : [],
    total_item_count: count,
  }
}

const originalCartContext = 'a'.repeat(64)
const currentCartContext = 'b'.repeat(64)

function cartReply(count = 0, context = originalCartContext) {
  return Response.json(cart(count), { headers: { 'X-Cart-Context': context } })
}

function error(code: string, message: string, status: number, details?: Record<string, unknown>) {
  return Response.json({ error: { code, message, details } }, { status })
}

function added(count: number, stock: number, replayed = false) {
  return Response.json({ cart: cart(count), sku_id: 'mug-oat-250', available_quantity: stock }, {
    headers: replayed ? { 'Idempotency-Replayed': 'true' } : {},
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

type ServerHandlers = {
  product?: () => Response | Promise<Response>;
  cart?: () => Response | Promise<Response>;
  post?: (request: RequestInit) => Response | Promise<Response>;
}

function serve(handlers: ServerHandlers = {}) {
  const post = vi.fn(handlers.post ?? (() => added(1, 7)))
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit) => {
    if (input === '/api/products/silt-mug') return handlers.product?.() ?? Response.json(product)
    if (input === '/api/cart') return handlers.cart?.() ?? cartReply()
    if (input === '/api/cart/items' && init.method === 'POST') return post(init)
    throw new Error(`Unexpected request to ${input}`)
  }))
  return post
}

const radio = (name: string) => screen.getByRole('radio', { name })
const addButton = () => screen.getByRole('button', { name: 'Add to cart' })
const increase = () => screen.getByRole('button', { name: 'Increase quantity' })
const quantity = () => screen.getByLabelText('Quantity', { selector: 'output' })
const cartBadge = () => within(screen.getByRole('banner')).getByText(/^[0-9]+$/)

async function chooseOat250(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('heading', { name: product.name })
  await user.click(radio('Oat'))
  await user.click(radio('250 mL'))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('variant product page', () => {
  it('updates the resolved SKU image, price and stock and clamps the quantity', async () => {
    serve()
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: product.name })
    expect(addButton()).toBeDisabled()
    expect(screen.getByText('Choose a glaze and capacity.')).toBeInTheDocument()

    await user.click(radio('Oat'))
    await user.click(radio('350 mL'))
    expect(screen.getByText('A$28.00')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', '/images/oat-350.webp')
    expect(screen.getByText('12 in stock')).toBeInTheDocument()
    await user.click(increase())
    await user.click(increase())
    expect(quantity()).toHaveTextContent('3')

    await user.click(radio('Moss'))
    expect(screen.getByText('A$29.00')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', '/images/moss-350.webp')
    expect(screen.getByText('1 in stock')).toBeInTheDocument()
    expect(quantity()).toHaveTextContent('1')
    expect(increase()).toBeDisabled()
  })

  it('disables missing and disabled combinations but lets the shopper inspect out-of-stock SKUs', async () => {
    const post = serve()
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('heading', { name: product.name })
    await user.click(radio('450 mL'))
    expect(radio('Moss')).toBeDisabled()
    expect(radio('Ink')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Clear selection' }))
    await user.click(radio('Ink'))
    expect(radio('250 mL')).toBeEnabled()
    await user.click(radio('250 mL'))
    expect(screen.getByText('Out of stock')).toBeInTheDocument()
    expect(screen.getByRole('img')).toHaveAttribute('src', '/images/ink-250.webp')
    expect(addButton()).toBeDisabled()
    expect(post).not.toHaveBeenCalled()
  })

  it('recovers from a product-load failure without refreshing the page', async () => {
    const initial = deferred<Response>()
    const getProduct = vi.fn((): Response | Promise<Response> => Response.json(product))
      .mockImplementationOnce(() => initial.promise)
    serve({ product: getProduct })
    const user = userEvent.setup()
    render(<App />)
    expect(screen.getByText('Loading product…')).toBeInTheDocument()
    initial.resolve(error('internal_error', 'Service unavailable', 500))
    expect(await screen.findByRole('alert')).toHaveTextContent('Please try again')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('heading', { name: product.name })).toBeInTheDocument()
    expect(getProduct).toHaveBeenCalledTimes(2)
  })

  it('sends only one request when two submissions arrive before React disables the button', async () => {
    const pending = deferred<Response>()
    const post = serve({ post: () => pending.promise })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    const form = screen.getByRole('form', { name: 'Product options and purchase' })

    act(() => { fireEvent.submit(form); fireEvent.submit(form) })
    expect(post).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Adding to cart…' })).toBeDisabled()
    pending.resolve(added(1, 7))
    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    expect(cartBadge()).toHaveTextContent('1')
    expect(screen.getByText('7 in stock')).toBeInTheDocument()
  })

  it('replaces stale inventory after a stock conflict and uses a new key for the next add', async () => {
    const reply = vi.fn(() => added(1, 0)).mockImplementationOnce(() => error(
      'insufficient_stock', 'Not enough stock.', 409, { sku_id: 'mug-oat-250', available_quantity: 1 },
    ))
    const post = serve({ post: reply })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(increase())
    await user.click(addButton())
    expect(await screen.findByText(/Stock changed/)).toBeInTheDocument()
    expect(quantity()).toHaveTextContent('1')
    expect(increase()).toBeDisabled()
    expect(screen.getByText('1 in stock')).toBeInTheDocument()

    await user.click(addButton())
    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    expect(screen.getByText('Out of stock')).toBeInTheDocument()
    const [first, second] = post.mock.calls.map(([request]) => request)
    expect(new Headers(first.headers).get('Idempotency-Key')).not.toBe(new Headers(second.headers).get('Idempotency-Key'))
    expect(second.body).toBe(JSON.stringify({ sku_id: 'mug-oat-250', quantity: 1 }))
  })

  it('retries an uncertain write with the same key and reads fresh data after replay', async () => {
    const updated = { ...product, skus: product.skus.map((item) => item.id === 'mug-oat-250'
      ? { ...item, available_quantity: 0 } : item) }
    const post = serve({
      product: vi.fn(() => Response.json(updated)).mockImplementationOnce(() => Response.json(product)),
      cart: vi.fn(() => cartReply(4)).mockImplementationOnce(() => cartReply()),
      post: vi.fn(() => added(1, 7, true)).mockImplementationOnce(() => error('internal_error', 'Unexpected error.', 500)),
    })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(addButton())
    expect(await screen.findByText(/couldn’t confirm the add/)).toBeInTheDocument()
    expect(addButton()).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Retry add' }))

    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(2)
    const [first, second] = post.mock.calls.map(([request]) => request)
    expect(new Headers(first.headers).get('Idempotency-Key')).toBeTruthy()
    expect(new Headers(second.headers).get('Idempotency-Key')).toBe(new Headers(first.headers).get('Idempotency-Key'))
    expect(new Headers(first.headers).get('X-Cart-Context')).toBe(originalCartContext)
    expect(new Headers(second.headers).get('X-Cart-Context')).toBe(originalCartContext)
    expect(second.body).toBe(first.body)
    expect(cartBadge()).toHaveTextContent('4')
    expect(screen.getByText('Out of stock')).toBeInTheDocument()
  })

  it('refreshes a changed cart without resending the uncertain add into it', async () => {
    const getCart = vi.fn(() => cartReply(0, currentCartContext)).mockImplementationOnce(() => cartReply())
    const post = serve({
      cart: getCart,
      post: vi.fn(() => added(1, 6))
        .mockRejectedValueOnce(new TypeError('The response was lost.'))
        .mockImplementationOnce(() => error('cart_context_changed', 'The cart session has changed.', 409)),
    })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(addButton())
    await user.click(await screen.findByRole('button', { name: 'Retry add' }))

    expect(await screen.findByText(/Your cart session changed/)).toBeInTheDocument()
    expect(getCart).toHaveBeenCalledTimes(2)
    expect(post).toHaveBeenCalledTimes(2)
    expect(cartBadge()).toHaveTextContent('0')
    expect(screen.queryByRole('button', { name: 'Retry add' })).not.toBeInTheDocument()

    await user.click(addButton())
    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    const [first, retry, next] = post.mock.calls.map(([request]) => new Headers(request.headers))
    expect(retry.get('X-Cart-Context')).toBe(originalCartContext)
    expect(retry.get('Idempotency-Key')).toBe(first.get('Idempotency-Key'))
    expect(next.get('X-Cart-Context')).toBe(currentCartContext)
    expect(next.get('Idempotency-Key')).not.toBe(first.get('Idempotency-Key'))
  })

  it('moves keyboard focus to retry after an uncertain add and restores it after success', async () => {
    const first = deferred<Response>()
    const retry = deferred<Response>()
    serve({ post: vi.fn(() => retry.promise).mockReturnValueOnce(first.promise) })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    addButton().focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('button', { name: 'Adding to cart…' })).toBeDisabled()
    first.resolve(error('internal_error', 'Unexpected error.', 500))
    expect(await screen.findByRole('button', { name: 'Retry add' })).toHaveFocus()

    await user.keyboard('{Enter}')
    retry.resolve(added(1, 7))
    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    expect(addButton()).toHaveFocus()
  })

  it('lets the shopper correct a validation failure without losing the selected SKU', async () => {
    serve({ post: () => error('validation_error', 'The requested quantity is invalid.', 422) })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(addButton())
    expect(await screen.findByText('The requested quantity is invalid.')).toBeInTheDocument()
    expect(radio('250 mL')).toBeChecked()
    expect(radio('Oat')).toBeChecked()
    expect(addButton()).toBeEnabled()
    expect(cartBadge()).toHaveTextContent('0')
  })

  it('only retries reads if a confirmed replay is followed by a failed refresh', async () => {
    const updated = { ...product, skus: product.skus.map((item) => item.id === 'mug-oat-250'
      ? { ...item, available_quantity: 7 } : item) }
    const post = serve({
      product: vi.fn(() => Response.json(updated))
        .mockImplementationOnce(() => Response.json(product))
        .mockImplementationOnce(() => error('internal_error', 'Unexpected error.', 500)),
      cart: vi.fn(() => cartReply(1)).mockImplementationOnce(() => cartReply()),
      post: () => added(1, 7, true),
    })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(addButton())
    expect(await screen.findByText(/Added to your cart.*couldn’t refresh/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh stock and cart' }))

    expect(await screen.findByText('Added to your cart.')).toBeInTheDocument()
    expect(cartBadge()).toHaveTextContent('1')
    expect(screen.getByText('7 in stock')).toBeInTheDocument()
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('shows an invalid combination if the selected SKU disappears during a refresh', async () => {
    const updated = { ...product, skus: product.skus.filter((item) => item.id !== 'mug-oat-250') }
    serve({
      product: vi.fn(() => Response.json(updated)).mockImplementationOnce(() => Response.json(product)),
      post: () => error('sku_not_found', 'SKU not found.', 404),
    })
    const user = userEvent.setup()
    render(<App />)
    await chooseOat250(user)
    await user.click(addButton())
    expect(await screen.findByText('This combination is unavailable.')).toBeInTheDocument()
    expect(addButton()).toBeDisabled()
    expect(radio('250 mL')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(screen.getByText('Choose a glaze and capacity.')).toBeInTheDocument()
  })
})
