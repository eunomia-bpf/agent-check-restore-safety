import Lake

open Lake DSL

package «authority-continuity» where
  version := v!"0.1.0"

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.30.0"

lean_lib AuthorityContinuity where
  globs := #[.submodules `AuthorityContinuity]
