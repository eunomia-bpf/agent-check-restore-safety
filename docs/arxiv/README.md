# arXiv submission package

Build and verify the upload archive from the repository root:

```sh
make arxiv-submission
```

This creates `arxiv-submission.tar.gz`. The build script stages only the files
needed by the paper, compiles the public version, includes a matching
`main.bbl`, extracts the resulting archive into a clean directory, and compiles
it again. The tracked conference source remains anonymous; the archive includes
`arxiv-config.tex`, which enables the author block and adds this public GitHub
repository directly to the abstract:

<https://github.com/eunomia-bpf/agent-check-restore-safety>

Suggested submission settings:

- TeX processor: `pdfLaTeX`
- Top-level file: `main.tex`
- Primary category: `cs.CR` (Cryptography and Security)
- Possible cross-list: `cs.LO` (Logic in Computer Science)
- License: choose the license agreed by all authors

Before completing the submission, compare arXiv's rendered PDF with the locally
verified PDF and paste the title, author list, and abstract from the public
version. Include the final sentence of the abstract so the arXiv metadata also
points readers to the GitHub repository.
