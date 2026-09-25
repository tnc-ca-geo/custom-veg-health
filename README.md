# custom-veg-health

NDVI, NDMI and water-year precipitation for your own polygons, calculated the same way as The Nature Conservancy's [GDE Pulse](https://gde.codefornature.org).

GDE Pulse tracks vegetation health for about 100,000 mapped groundwater dependent ecosystems in California. This tool gives you the same annual series for polygons you draw, such as updated GDE boundaries for a groundwater sustainability plan.

For each polygon and year it reports:

| Column | Meaning |
|---|---|
| `polygon_id` | the value of your ID field |
| `year` | year of the dry-season (June 1 - September 30) Landsat composite |
| `ndvi` | mean NDVI: greenness |
| `ndmi` | mean NDMI: vegetation moisture |
| `precip_in` | PRISM precipitation, in inches, for the water year ending that year |

Composites start in 1985, and a new year is added about once a year.

## Install

Needs Python 3.10 or later, and is developed and tested on 3.13.

**1. Open a terminal.**

- **Windows:** click Start, type `PowerShell`, and open **Windows PowerShell**.
- **macOS:** open **Terminal** (in Applications > Utilities).
- **Linux:** open your usual terminal.

Type each command below and press Enter.

**2. Check your Python version.**

- Windows: `py --version`
- macOS and Linux: `python3 --version`

It should print `Python 3.10` or newer (3.13 is best). If the command isn't found, or on Windows it opens the Microsoft Store, install Python 3.13 from [python.org](https://www.python.org/downloads/), then close and reopen the terminal. On Debian/Ubuntu you also need the `python3.13-venv` package.

**3. Create an environment and install the tool.** The environment keeps this tool's packages separate from the rest of your computer.

Windows (PowerShell):

```powershell
py -m venv "$HOME\Documents\veg-health-env"
& "$HOME\Documents\veg-health-env\Scripts\Activate.ps1"
python -m pip install git+https://github.com/tnc-ca-geo/custom-veg-health.git
```

Keep the `&` and the quotes on the second line: PowerShell won't run a path that starts with `$HOME` without them.

macOS and Linux:

```bash
python3 -m venv ~/veg-health-env
source ~/veg-health-env/bin/activate
python -m pip install git+https://github.com/tnc-ca-geo/custom-veg-health.git
```

Once activated, your prompt starts with `(veg-health-env)`. **Run the activate line (the second line above) again each time you open a new terminal**, before using the tool. Type `deactivate` to leave. If you prefer conda or pipx, those work too.

**4. Check it worked:**

```
python -m custom_veg_health --version
```

It prints the version, for example `custom-veg-health 0.1.0`. A shorter `custom-veg-health` command is installed too, but `python -m custom_veg_health` works in every setup, so the examples below use it.

## Earth Engine access

The tool runs on [Google Earth Engine](https://earthengine.google.com) under your own Google account. The imagery it reads is public.

1. **Register a Cloud project.** Earth Engine requests are billed to a Google Cloud project. Register one at <https://console.cloud.google.com/earth-engine>, following Google's [access guide](https://developers.google.com/earth-engine/guides/access), which explains which option suits your organization. Note the project ID (for example `my-veg-health`) it is not always the same as the display name.

   If you need a commercial plan, the pay-as-you-go [Limited plan](https://cloud.google.com/earth-engine/pricing) is enough for this tool. 300 polygons over 41 years used about 1 EECU-hour, roughly $0.40 at September 2026 rates/billing structure.

2. **Sign in.** The first time you run the tool with no arguments (see [Run](#run)), it offers to sign you in and opens a browser. To sign in on its own instead, with your environment activated:

   ```
   python -c "import ee; ee.Authenticate()"
   ```

   Your sign-in is saved under your home folder (`~/.config/earthengine/`, or `%USERPROFILE%\.config\earthengine` on Windows) and lasts until you revoke it. You do not need the Google Cloud SDK (`gcloud`).

## Run

```
python -m custom_veg_health
```

With no arguments, the tool walks you through each choice:
- your polygon file (and layer, if there are several)
- the ID field (fields with blanks or repeats are greyed out)
- your Earth Engine project (it offers to sign you in if needed)
- which years, whether to include precipitation, and where to save

Before running, it shows a time estimate and the equivalent command.

To skip the prompts for example in a script, pass the options directly:

```
python -m custom_veg_health --polygons my_gdes.gpkg --id-field POLYGON_ID --project my-ee-project
```

This writes `my_gdes_veg_health.csv`. Other options:

```bash
--years 2010-2025        # or 2015,2020,2025. Default is every available year
--output results.csv
--layer NAME             # for files with several layers
--no-precip
```

Polygons can be a GeoPackage, shapefile (or a zip of one), GeoJSON, file geodatabase, or anything else GDAL reads, in any coordinate system recognized by GDAL. IDs must be unique. The tool repairs invalid geometries and tells you what it changed.

To try it on ten GDE polygons from the Natural Communities dataset:

```
git clone https://github.com/tnc-ca-geo/custom-veg-health
cd custom-veg-health
python -m custom_veg_health --polygons examples/example.gpkg --id-field polygon_id --project my-ee-project --years 2020-2025
```

### From Python

```python
import custom_veg_health as cvh

cvh.initialize('my-ee-project')
polygons = cvh.read_polygons('my_gdes.gpkg', id_field='POLYGON_ID')
years = cvh.resolve_years(cvh.parse_years('2010-2025'), cvh.available_years())
cvh.extract(polygons, years).to_csv('results.csv', index=False)
```

## How the numbers are made

Each value is the area-weighted mean over 30 m Landsat pixels of a medoid composite of the June-September dry season. Settings match GDE Pulse: for polygons that are also in GDE Pulse, results agree with the published values to within 0.001 for NDVI and NDMI and to the inch for precipitation (`tests/test_parity_ee.py`).

A few things worth knowing:

- Partial pixels count in proportion to how much of them the polygon covers.
  For a narrow riparian strip, an edge pixel that is mostly neighbouring field
  or road still contributes part of its value.
- A blank value means no pixel counted: the polygon is far smaller than a
  30 m pixel (900 m2), or every overlapping pixel was masked by cloud that year.
- Precipitation is the water year ending in that year (October to
  September), from 4 km PRISM data, so nearby small polygons often share a value.
  It is left blank for a water year that has not finished, and PRISM keeps
  revising the most recent six months.
- The full method is on the GDE Pulse
  [methodology page](https://gde.codefornature.org/#/methodology).

These are indicators, not measurements of groundwater use. NDVI and NDMI respond to drought, fire, disease and land management as well as to groundwater. Pair them with precipitation, groundwater levels and knowledge of the site before drawing conclusions.

## If something goes wrong

| Message | What to do |
|---|---|
| `running scripts is disabled on this system` (Windows, when activating) | Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` once, then run the activate line again. |
| `No module named custom_veg_health`, or `not recognized` / `command not found` | The environment isn't active in this terminal. Run the activate line from [Install](#install) again. |
| Not sure the environment is active | `python -c "import sys; print(sys.prefix)"` should print your `veg-health-env` folder. If it prints something else, activate first, then reinstall. |
| `Cannot find command 'git'` while installing | Install without Git: `python -m pip install https://github.com/tnc-ca-geo/custom-veg-health/archive/refs/heads/main.zip` |
| `No Earth Engine credentials were found` | Pass `--authenticate`, or run the tool with no arguments and it offers to sign you in. |
| `Earth Engine needs a Google Cloud project` | Pass `--project` or set `EE_PROJECT`. |
| `not registered` / `Earth Engine API has not been used in project ...` | Register that project. Check you used the project ID, not its display name. |
| `Caller does not have required permission` | Check your account belongs to the project and its Earth Engine access is active. |
| `No composite for 2026` | That year is not published yet. A new year is added about once a year, after the dry season. |
| `redirect_uri_mismatch` while signing in | You are on a machine without a browser: `python -c "import ee; ee.Authenticate(quiet=True)"` |

## A few hundred polygons, not a hundred thousand

Polygons are sent to Earth Engine with each request. That keeps setup simple (no asset uploads or Cloud Storage) and suits jobs of a few hundred polygons. Very large jobs such as statewide runs should use custom approaches.

## Development Information

Tests can be run as following:

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest                                  # offline tests, a second or two
EE_PROJECT=my-ee-project .venv/bin/pytest -m ee   # calls Earth Engine (needs an internet connection)
```

| File | What it holds |
|---|---|
| `src/custom_veg_health/imagery.py` | asset names, year discovery, the NDVI/NDMI and precipitation images |
| `src/custom_veg_health/zonal.py` | reading and checking polygons, chunking, `reduceRegions`, retries, the output table |
| `src/custom_veg_health/cli.py` | command line flags |
| `src/custom_veg_health/interactive.py` | the guided prompts |
| `tests/data/published_example.csv` | GDE Pulse's own values for `examples/example.gpkg`, taken from its bulk download |

Every test except `test_parity_ee.py` runs offline: Earth Engine is replaced by fakes, so the suite is fast and needs no credentials. `-m ee` opts into the live check that results still match published GDE Pulse values (first run takes a few minutes. Earth Engine caches, so repeat runs are quicker).

Worth knowing before changing things:

- New composite years appear on their own. `available_years()` lists the collection and reads years out of names like `Landsat_SR_medoid_2025_2025_152_273`, so nothing needs bumping each year as long as that naming holds.
- `--collection` is an undocumented flag for pointing at a different asset collection, which is handy for comparing against the older `projects/igde-work/raster-data/composite-collection` but not for normal users.
- Results match GDE Pulse because of `scale=30`, `crs='EPSG:4326'` and Earth Engine's default weighted mean, copied from the production pipeline. Changing any of them changes the numbers. `pytest -m ee` is what will catch if your changes drift from the publicly posted values.
- Problems a user can fix are raised as `SetupError`, and the message says how to fix them. The command line turns those into `error: ...` and exit code 2. Pleas continue to use this pattern.

## Credits and citation

- Composites: Ian Housman, RedCastle Resources, for The Nature Conservancy.
- GDE Pulse: Klausmeyer, K. R., T. Biswas, M. M. Rohde, F. Schuetzenmeister,
  N. Rindlaub, I. Housman and J. K. Howard. *GDE Pulse: Taking the Pulse of
  Groundwater Dependent Ecosystems with Satellite Data.* The Nature Conservancy,
  California. <https://gde.codefornature.org>
- Precipitation: PRISM Climate Group, Oregon State University.

## License

[MIT](LICENSE)
