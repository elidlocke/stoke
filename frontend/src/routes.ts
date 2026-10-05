/** A customer's profile URL. It uses the opaque id, so URLs and history never contain an email. */
export function customerPath(customerId: string): string {
  return `/customers/${encodeURIComponent(customerId)}`
}
