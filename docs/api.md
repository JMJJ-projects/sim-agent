# photonsim API reference

`photonsim` is a Monte Carlo simulator of mono-energetic photons hitting a 1D stack of slab
layers at normal incidence. Each photon ends `transmitted` (leaves the back face), `reflected`
(back-scattered out of the front face) or `absorbed`.

Simplified physics: exponential free path from the layer's `mu_total`; at each interaction the
photon is absorbed with probability `mu_abs/mu_total`, else scattered isotropically with no
energy loss. Transmission therefore includes scattered photons. Units: cm, MeV.

## Materials

| name | energy range (MeV) |
|---|---|
| `aluminium` | 0.1 to 10 |
| `concrete` | 0.1 to 10 |
| `iron` | 0.1 to 10 |
| `lead` | 0.1 to 10 |
| `polyethylene` | 0.1 to 10 |
| `water` | 0.1 to 10 |

Data: NIST SRD 126 (Hubbell & Seltzer). Outside the range: `ValueError`.

## Functions and classes

### `Layer(material: str, thickness_cm: float)`

One homogeneous slab layer.

Args:
    material: material name, one of `list_materials()` (case-insensitive).
    thickness_cm: layer thickness in cm, > 0.

### `Slab(layers: list[Layer])`

A stack of layers; photons enter the first layer at normal incidence.

Args:
    layers: non-empty list of `Layer`, front (beam side) first.

### `simulate(slab: Slab, energy_mev: float, n_photons: int, seed: int | None = None) -> Result`

Simulate `n_photons` photons of `energy_mev` MeV hitting `slab` at normal incidence.

The same `seed` always gives the same `Result`. Raises `ValueError` for an invalid
slab, an energy outside a layer material's data range, or `n_photons < 1`.

### `sweep(build: Callable[[float], Slab], values: list[float], energy_mev: float, n_photons: int, seed: int | None = None) -> list[tuple[float, Result]]`

Run `simulate(build(v), energy_mev, n_photons, seed)` for each `v` in `values`.

Returns `[(v, Result), ...]` in the order of `values`. With a seed, every point uses the
same seed (common random numbers), which makes curves smoother and monotonic trends clearer.

### `list_materials() -> list[str]`

Return the names of all available materials, sorted.

### `energy_range(material: str) -> tuple[float, float]`

Return `(min_mev, max_mev)`, the energy range covered by the data for `material`.

### `Result`

Outcome of `simulate`: fractions of photons by fate, summing to 1.

Attributes (all float except `n_photons`):
    transmitted: fraction leaving the back face (includes scattered photons).
    reflected: fraction back-scattered out of the front face.
    absorbed: fraction absorbed inside the slab.
    n_photons: number of photons simulated.
    energy_mev: photon energy in MeV.
    stderr_transmitted: binomial standard error of `transmitted`.
    stderr_reflected: binomial standard error of `reflected`.
    stderr_absorbed: binomial standard error of `absorbed`.

`to_dict()` returns these fields as a dict.

## Example

```python
import photonsim as ps

slab = ps.Slab([ps.Layer("water", 5.0), ps.Layer("lead", 1.0)])
res = ps.simulate(slab, energy_mev=1.0, n_photons=100_000, seed=1)
print(res.transmitted, res.stderr_transmitted)

curve = ps.sweep(lambda t: ps.Slab([ps.Layer("lead", t)]), [1, 2, 4], 1.0, 20_000, seed=1)
for thickness, r in curve:
    print(thickness, r.transmitted)
```

Invalid arguments raise `ValueError` with a message naming the argument and valid options.
