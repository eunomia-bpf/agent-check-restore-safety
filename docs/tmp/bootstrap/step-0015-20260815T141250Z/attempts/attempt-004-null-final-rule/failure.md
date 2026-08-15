# Attempt 004: final Rule empty-set encoding

The live run again completed every condition. The independent checker passed
the upstream, Mongo, observer, query settlement, and History checks, then
rejected the final State because `rule.allow` was JSON `null` rather than the
required empty array `[]`.

The Rule was semantically empty. `State.Clone` had converted a non-nil empty
slice into nil when serving the API snapshot. The generic clone and activation
paths now preserve an empty array, with a kernel regression test. The checker
was not relaxed.
