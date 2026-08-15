# Attempt 003: ambiguous empty fact encoding

The full live runner passed: raw retry produced two Mongo documents, the
old-version condition retained v1 without a result, and the runtime deleted v1
then recovered the committed Operation by query without redispatch.

The independent checker correctly rejected the retained observer evidence.
For zero and multiple matches, the observer encoded its nested empty fact set
as JSON `null`; the fixed evidence contract requires the unambiguous array
`[]`. The observer now constructs a non-nil empty slice, and a unit test binds
that representation. No checker condition was relaxed.
