import { z } from 'zod'

const CART_CONTEXT_HEADER = 'X-Cart-Context'
const cartContextSchema = z.string().regex(/^[a-f0-9]{64}$/)
const nonNegativeInteger = z.number().int().nonnegative()

const skuSchema = z.object({
  id: z.string(),
  option_values: z.record(z.string(), z.string()),
  price_minor: nonNegativeInteger,
  available_quantity: nonNegativeInteger,
  image_url: z.string().startsWith('/images/'),
  is_available: z.boolean(),
})

const productSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  currency: z.string().regex(/^[A-Z]{3}$/),
  options: z.array(z.object({
    id: z.string(),
    label: z.string(),
    values: z.array(z.object({ id: z.string(), label: z.string() })).min(1),
  })).min(1),
  skus: z.array(skuSchema),
})

const cartSchema = z.object({
  items: z.array(z.object({
    sku_id: z.string(),
    quantity: z.number().int().positive(),
    unit_price_minor: nonNegativeInteger,
    currency: z.string(),
  })),
  total_item_count: nonNegativeInteger,
})

const addResultSchema = z.object({
  cart: cartSchema,
  sku_id: z.string(),
  available_quantity: nonNegativeInteger,
})

const errorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.string(), z.unknown()).optional(),
  }),
})

export type Product = z.infer<typeof productSchema>
export type Sku = z.infer<typeof skuSchema>
export type Cart = z.infer<typeof cartSchema>

export interface CartSession {
  cart: Cart
  context: string
}

export interface AddAttempt {
  skuId: string
  quantity: number
  key: string
  cartContext: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}) {
  const timeout = AbortSignal.timeout(10_000)
  const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout
  const response = await fetch(path, { ...init, cache: 'no-store', credentials: 'same-origin', signal })
  const payload: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    const parsed = errorSchema.safeParse(payload)
    const error = parsed.success ? parsed.data.error : undefined
    throw new ApiError(response.status, error?.code ?? 'http_error', error?.message ?? 'Request failed.', error?.details)
  }
  return { data: schema.parse(payload), response }
}

export async function getProduct(signal?: AbortSignal): Promise<Product> {
  return (await request('/api/products/silt-mug', productSchema, { signal })).data
}

export async function getCart(signal?: AbortSignal): Promise<CartSession> {
  const { data, response } = await request('/api/cart', cartSchema, { signal })
  return { cart: data, context: cartContextSchema.parse(response.headers.get(CART_CONTEXT_HEADER)) }
}

export async function addCartItem(attempt: AddAttempt) {
  const { data, response } = await request('/api/cart/items', addResultSchema, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': attempt.key,
      [CART_CONTEXT_HEADER]: attempt.cartContext,
    },
    body: JSON.stringify({ sku_id: attempt.skuId, quantity: attempt.quantity }),
  })
  if (data.sku_id !== attempt.skuId) throw new Error('The response refers to a different SKU.')
  return { ...data, replayed: response.headers.get('Idempotency-Replayed') === 'true' }
}
