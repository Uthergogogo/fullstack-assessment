import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, addCartItem, getCart, getProduct, type AddAttempt, type CartSession, type Product } from './api'
import { boundQuantity, isOptionAvailable, previewSku, resolveVariant, withStock, type Selection } from './variants'

type Feedback = { tone: 'success' | 'error'; message: string }
type Recovery = { kind: 'add'; attempt: AddAttempt } | { kind: 'refresh'; feedback: Feedback }

const ADDED: Feedback = { tone: 'success', message: 'Added to your cart.' }

export function PageHeader({ count }: { count?: number }) {
  return (
    <header className="site-header">
      <div className="header-content">
        <span className="wordmark">silt<span>.</span></span>
        <span className="cart-count">
          <span className="bag-icon" aria-hidden="true" />
          Cart <strong>{count ?? '–'}</strong>
        </span>
      </div>
    </header>
  )
}

export function ProductPage({ initialProduct, initialCartSession }: {
  initialProduct: Product
  initialCartSession: CartSession
}) {
  const [product, setProduct] = useState(initialProduct)
  const [cartSession, setCartSession] = useState(initialCartSession)
  const [selection, setSelection] = useState<Selection>({})
  const [requestedQuantity, setQuantity] = useState(1)
  const [working, setWorking] = useState<'add' | 'refresh' | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [recovery, setRecovery] = useState<Recovery | null>(null)
  const inFlight = useRef(false)
  const submitButton = useRef<HTMLButtonElement>(null)
  const retryButton = useRef<HTMLButtonElement>(null)
  const feedbackRegion = useRef<HTMLDivElement>(null)
  const focusOrigin = useRef<Element | null>(null)

  const variant = resolveVariant(product, selection)
  const sku = 'sku' in variant ? variant.sku : undefined
  const image = sku ?? previewSku(product, selection)
  const imageOptions = product.options.map((option) => (
    option.values.find((value) => value.id === image?.option_values[option.id])?.label
  )).filter(Boolean).join(', ')
  const prices = product.skus.filter((item) => item.is_available).map((item) => item.price_minor)
  const price = sku?.price_minor ?? (prices.length ? Math.min(...prices) : undefined)
  const formattedPrice = price === undefined ? null : new Intl.NumberFormat('en-US', {
    style: 'currency', currency: product.currency,
  }).format(price / 100)
  const quantity = boundQuantity(requestedQuantity, variant)
  const locked = working !== null || recovery !== null
  const canAdd = variant.state === 'in-stock' && !locked

  useEffect(() => {
    const origin = focusOrigin.current
    if (working || !origin) return
    focusOrigin.current = null
    // Disabling or removing a focused button can send focus back to the document body.
    if (document.activeElement !== origin && document.activeElement !== document.body) return
    const target = recovery ? retryButton.current : canAdd ? submitButton.current : feedbackRegion.current
    target?.focus()
  }, [working, recovery, canAdd])

  function select(next: Selection) {
    setSelection(next)
    setQuantity((previous) => boundQuantity(previous, resolveVariant(product, next)))
    setFeedback(null)
  }

  function runLocked(kind: 'add' | 'refresh', action: () => Promise<void>) {
    // Two events can arrive before React applies the pending button state.
    if (inFlight.current) return
    inFlight.current = true
    const focused = document.activeElement
    focusOrigin.current = focused === submitButton.current || focused === retryButton.current ? focused : null
    setWorking(kind)
    setRecovery(null)
    setFeedback(null)
    void action().finally(() => {
      inFlight.current = false
      setWorking(null)
    })
  }

  async function refreshSnapshot(notice: Feedback) {
    try {
      const [latestProduct, latestCartSession] = await Promise.all([getProduct(), getCart()])
      setProduct(latestProduct)
      setCartSession(latestCartSession)
      setQuantity((previous) => boundQuantity(previous, resolveVariant(latestProduct, selection)))
      setFeedback(notice)
    } catch {
      setFeedback({ tone: 'error', message: `${notice.message} We couldn’t refresh the stock and cart.` })
      setRecovery({ kind: 'refresh', feedback: notice })
    }
  }

  function applyStock(skuId: string, available: number) {
    setProduct((current) => withStock(current, skuId, available))
    if (sku?.id === skuId) setQuantity((previous) => Math.max(1, Math.min(previous, available)))
  }

  async function sendAdd(attempt: AddAttempt) {
    try {
      const result = await addCartItem(attempt)
      if (result.replayed) {
        // The replay is proof of success. Its stock and cart are historical snapshots.
        await refreshSnapshot(ADDED)
      } else {
        setCartSession((current) => ({ ...current, cart: result.cart }))
        applyStock(result.sku_id, result.available_quantity)
        setFeedback(ADDED)
      }
    } catch (error) {
      if (!(error instanceof ApiError) || error.status >= 500 || error.status === 408) {
        setFeedback({ tone: 'error', message: 'We couldn’t confirm the add. Retry to check the same request.' })
        setRecovery({ kind: 'add', attempt })
      } else if (error.code === 'insufficient_stock') {
        const stock = error.details?.available_quantity
        const notice: Feedback = { tone: 'error', message: 'Stock changed. Check the available quantity and try again.' }
        if (error.details?.sku_id === attempt.skuId && typeof stock === 'number' && Number.isSafeInteger(stock) && stock >= 0) {
          applyStock(attempt.skuId, stock)
          setFeedback(notice)
        } else {
          await refreshSnapshot(notice)
        }
      } else if (error.code === 'sku_unavailable' || error.code === 'sku_not_found') {
        await refreshSnapshot({ tone: 'error', message: 'This combination is no longer available. Choose another.' })
      } else if (error.code === 'cart_session_required' || error.code === 'cart_context_changed') {
        await refreshSnapshot({
          tone: 'error', message: 'Your cart session changed. Review the current cart and stock before adding again.',
        })
      } else {
        setFeedback({ tone: 'error', message: error.message })
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canAdd || variant.state !== 'in-stock' || inFlight.current) return
    const attempt = { skuId: variant.sku.id, quantity, key: crypto.randomUUID(), cartContext: cartSession.context }
    runLocked('add', () => sendAdd(attempt))
  }

  function retry() {
    if (recovery?.kind === 'add') runLocked('add', () => sendAdd(recovery.attempt))
    if (recovery?.kind === 'refresh') runLocked('refresh', () => refreshSnapshot(recovery.feedback))
  }

  return (
    <>
      <PageHeader count={cartSession.cart.total_item_count} />
      <main className="product-layout">
        <div className="product-image">
          {image && <img key={image.id} src={image.image_url} alt={`${product.name} in ${imageOptions}`} width={1254} height={1254} />}
        </div>
        <section className="product-info" aria-labelledby="product-name">
          <h1 id="product-name">{product.name}</h1>
          {formattedPrice && <p className="product-price">{sku ? '' : 'From '}{formattedPrice}</p>}
          <p className="product-description">{product.description}</p>

          <form onSubmit={submit} className="purchase-form" aria-label="Product options and purchase">
            {product.options.map((option) => (
              <fieldset key={option.id} className="option-group" disabled={locked}>
                <legend>{option.label}</legend>
                <div className="option-list">
                  {option.values.map((value) => (
                    <label className="option-chip" key={value.id}>
                      <input
                        type="radio"
                        name={option.id}
                        value={value.id}
                        checked={selection[option.id] === value.id}
                        disabled={!isOptionAvailable(product, selection, option.id, value.id)}
                        onChange={() => select({ ...selection, [option.id]: value.id })}
                      />
                      {option.id === 'color' && <span className={`swatch swatch-${value.id}`} aria-hidden="true" />}
                      {value.label}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}

            <div className="availability-row">
              <p className={`availability availability-${variant.state}`} id="availability" role="status">
                {variant.state === 'in-stock' && `${variant.sku.available_quantity} in stock`}
                {variant.state === 'out-of-stock' && 'Out of stock'}
                {variant.state === 'incomplete' && 'Choose a glaze and capacity.'}
                {variant.state === 'unavailable' && 'This combination is unavailable.'}
              </p>
              {Object.values(selection).some(Boolean) && (
                <button className="text-button" type="button" disabled={locked} onClick={() => select({})}>
                  Clear selection
                </button>
              )}
            </div>

            <fieldset className="quantity-group">
              <legend>Quantity</legend>
              <div className="quantity-stepper">
                <button type="button" aria-label="Decrease quantity" disabled={!canAdd || quantity <= 1}
                  onClick={() => setQuantity(quantity - 1)}>−</button>
                <output aria-label="Quantity">{quantity}</output>
                <button type="button" aria-label="Increase quantity"
                  disabled={!canAdd || quantity >= (sku?.available_quantity ?? 0)}
                  onClick={() => setQuantity(quantity + 1)}>+</button>
              </div>
            </fieldset>

            <button ref={submitButton} type="submit" className="primary-button" disabled={!canAdd} aria-describedby="availability">
              {working === 'add' ? 'Adding to cart…' : 'Add to cart'}
            </button>
          </form>

          <div className="purchase-feedback" ref={feedbackRegion} tabIndex={-1}>
            <div role="status" aria-live="polite">
              {working === 'add' && <p>Adding to your cart…</p>}
              {working === 'refresh' && <p>Refreshing stock and cart…</p>}
              {feedback?.tone === 'success' && <p className="success-message">{feedback.message}</p>}
            </div>
            <div role="alert">
              {feedback?.tone === 'error' && <p className="error-message">{feedback.message}</p>}
            </div>
            {recovery && <button ref={retryButton} type="button" className="secondary-button" onClick={retry}>
              {recovery.kind === 'add' ? 'Retry add' : 'Refresh stock and cart'}
            </button>}
          </div>
        </section>
      </main>
    </>
  )
}
