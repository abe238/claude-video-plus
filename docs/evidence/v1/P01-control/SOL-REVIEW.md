# P01 Sol review

Status: **CHANGES REQUIRED — FIXES IMPLEMENTED, FINAL REVIEW PENDING**

First exact-tree review:

- Model: `gpt-5.6-sol`
- Session: `019f54d6-7120-70e1-a28b-3727081b91b3`
- Reviewed staged tree: `c3f2a32a21afdb420ce3d030c6bb3c00dcf595dd`
- Verdict: **CHANGES_REQUIRED**

Sol found seven blocking integrity gaps: source/caption identity validation, overlapping
artifact directories, tool probing before content pin verification, inherited Git controls,
overstated retry/cookie isolation, incomplete process-tree timeout cleanup, and missing live
execution proof. Terra implemented fixes and regression tests for all seven. The resulting
tree still requires a fresh exact-tree Sol verdict; no packet closure is asserted here.

Second exact-tree review:

- Model: `gpt-5.6-sol`
- Session: `019f54e7-188a-7c30-a2a6-0e7b0145feca`
- Reviewed staged tree: `01a5c54ecfa352723138d6bb8b216689d6530441`
- Verdict: **CHANGES_REQUIRED**

Sol found two P1 findings: caption identity was not tied to the subtitle actually consumed by
unchanged Control, and a SIGTERM-resistant descendant could survive when the leader exited and
closed its pipes. Terra has redesigned the caption receipt around post-run frozen
`_pick_subtitle` selection and added an unconditional final SIGKILL process-group step with
resistant-descendant regression coverage. This remediation requires another fresh Sol review;
no approval or closure is asserted here.

Third exact-tree review:

- Model: `gpt-5.6-sol`
- Session: `019f54f3-8386-74d3-90fb-45e273d0a7b4`
- Reviewed staged tree: `91505f8259d5b58e46beb5ad5118d730c67be738`
- Verdict: **CHANGES_REQUIRED**

Sol found that final-directory caption inspection could differ from bytes consumed before a
later yt-dlp call, and that undeclared source/invocation provenance fields were accepted. The
bounded remediation now snapshots VTTs synchronously inside a hash-recorded yt-dlp pass-through
wrapper before Control resumes, selects the consumed snapshot using frozen rules, and requires
exact provenance key sets. This smaller remediation requires a fresh independent verdict.

## Final approval

Model: `gpt-5.6-sol`

Session: `019f54fb-63e6-7ea2-937a-45f72809a318`

Approved staged tree: `60121e1316cde582fc61f44239e87dc3a17b76e8`

Final verdict: **APPROVE**
