# Long-Term Multi-Session 3D Reconstruction Under Substantial Appearance Change

Source code for the project page of *Long-Term Multi-Session 3D Reconstruction Under Substantial Appearance Change*.

## Updating Figures

Figures are converted from the paper's figure folder into `static/images/` (needs poppler's `pdftoppm` and Pillow):

```bash
python3 scripts/convert_figures.py /path/to/paper/figures
```

## Local Preview

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

If you find this work useful, please cite:
```bibtex
@article{gorry2026longterm,
    title={Long-Term Multi-Session 3D Reconstruction Under Substantial Appearance Change},
    author={Beverley Gorry and Tobias Fischer and Michael Milford and Alejandro Fontan},
    journal={arXiv preprint arXiv:2602.20584},
    year={2026},
}
```

# Website License
<a rel="license" href="http://creativecommons.org/licenses/by-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-sa/4.0/88x31.png" /></a><br /><br />This work is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0 International License</a>.
