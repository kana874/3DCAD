# Open CASCADE finite-parameter guard

The bundled engine reports Open CASCADE Technology 7.8.1. The file
`Geom_TrimmedCurve.cxx` is derived from the corresponding upstream source at
https://github.com/Open-Cascade-SAS/OCCT/blob/V7_8_1/src/Geom/Geom_TrimmedCurve.cxx
and retains its copyright and LGPL notices. `trim-finite.patch` records the
source-level change. OCCT's LGPL-2.1 and its special exception remain applicable;
the original engine's notices are preserved in the base image.

The build adapts the pinned WebAssembly binary instead of recompiling OCCT.
`scripts/patch_occt_wasm.py` verifies the complete original module and target
function hashes before adding an equivalent guard. Nonfinite inputs take the
existing equal-bound exception path; finite inputs are unchanged. The build
fails rather than patching a different engine version. The isolated real-WASM
test verifies NaN/infinity rejection and document transaction rollback.
