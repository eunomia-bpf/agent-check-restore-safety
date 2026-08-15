// Package provideradapter helps a versioned HTTP service implement the
// safe-change provider-adapter boundary.
//
// A Handler accepts only the runtime's stable Operation identity, content
// type, and stored body. It never gives a Driver the inbound HTTP request or
// its headers. Provider credentials therefore belong to the Driver's private
// startup configuration and are added only to a new provider request.
//
// The package validates and writes operation-receipt-v1 and
// operation-observation-v1 responses. It does not infer that a provider is
// safe to retry: that property depends on the provider's idempotency scope,
// retention, and request-binding semantics.
package provideradapter
