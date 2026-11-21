import { useEffect, useState } from 'react'
import { getCart, getProduct, type CartSession, type Product } from './api'
import { PageHeader, ProductPage } from './ProductPage'

type PageState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; product: Product; cartSession: CartSession }

export function App() {
  const [page, setPage] = useState<PageState>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    Promise.all([getProduct(signal), getCart(signal)]).then(
      ([product, cartSession]) => {
        if (!signal.aborted) setPage({ kind: 'ready', product, cartSession })
      },
      () => {
        if (!signal.aborted) {
          setPage({ kind: 'error', message: 'We couldn’t load the product and cart. Please try again.' })
          controller.abort()
        }
      },
    )
    return () => controller.abort()
  }, [attempt])

  if (page.kind === 'ready') {
    return <ProductPage initialProduct={page.product} initialCartSession={page.cartSession} />
  }

  return (
    <>
      <PageHeader />
      <main className="page-message">
        {page.kind === 'loading' ? (
          <p role="status">Loading product…</p>
        ) : (
          <>
            <h1>Product unavailable</h1>
            <p role="alert">{page.message}</p>
            <button className="primary-button" type="button" onClick={() => {
              setPage({ kind: 'loading' })
              setAttempt((previous) => previous + 1)
            }}>Try again</button>
          </>
        )}
      </main>
    </>
  )
}
