import type { Product, Sku } from './api'

export type Selection = Readonly<Record<string, string | undefined>>

export type Variant =
  | { state: 'incomplete' | 'unavailable' }
  | { state: 'out-of-stock' | 'in-stock'; sku: Sku }

function matchesSelection(product: Product, sku: Sku, selection: Selection): boolean {
  return product.options.every(({ id }) => !selection[id] || sku.option_values[id] === selection[id])
}

export function resolveVariant(product: Product, selection: Selection): Variant {
  if (product.options.some(({ id }) => !selection[id])) return { state: 'incomplete' }

  const sku = product.skus.find((candidate) => matchesSelection(product, candidate, selection))
  if (!sku?.is_available) return { state: 'unavailable' }
  return { state: sku.available_quantity > 0 ? 'in-stock' : 'out-of-stock', sku }
}

export function isOptionAvailable(product: Product, selection: Selection, optionId: string, valueId: string): boolean {
  const candidate = { ...selection, [optionId]: valueId }
  return product.skus.some((sku) => sku.is_available && matchesSelection(product, sku, candidate))
}

export function previewSku(product: Product, selection: Selection): Sku | undefined {
  const defaults = Object.fromEntries(product.options.map((option) => [option.id, option.values[0].id]))
  const matching = product.skus.filter((sku) => sku.is_available && matchesSelection(product, sku, selection))
  return matching.find((sku) => matchesSelection(product, sku, defaults)) ?? matching[0]
    ?? product.skus.find((sku) => sku.is_available && matchesSelection(product, sku, defaults))
    ?? product.skus.find((sku) => sku.is_available)
}

export function boundQuantity(quantity: number, variant: Variant): number {
  return variant.state === 'in-stock' ? Math.max(1, Math.min(quantity, variant.sku.available_quantity)) : 1
}

export function withStock(product: Product, skuId: string, stock: number): Product {
  return {
    ...product,
    skus: product.skus.map((sku) => sku.id === skuId ? { ...sku, available_quantity: stock } : sku),
  }
}
