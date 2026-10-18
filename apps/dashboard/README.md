# Dashboard (F9)

Install the dashboard dependencies:

```sh
pip install -e ".[dev,api]"
```

If you already have a virtual environment, reinstall after pulling this change so the packaged
`apps` module is available:

```sh
pip install -e ".[dev,api]"
```

Run the simulation:

```sh
ra-demo dashboard
```

Run with a webcam:

```sh
ra-demo dashboard --live --uri 0
```

Open the dashboard:

```sh
open http://127.0.0.1:8000
```
