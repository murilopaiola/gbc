From only the final landing SD, `time_scale` is usually not identifiable by itself. Inference: multiple combinations of `v_scale`, `wind_x_coeff`, `wind_y_coeff`, and `time_scale` can produce almost the same landing result, so the optimizer cannot separate them cleanly from one observed outcome.

The practical fix is to not try to “extract” `time_scale` directly. Use one of these instead:

The simplest path is to remove `time_scale` as a separate fitted parameter and absorb it into the wind coefficients per band. So you fit `v_scale`, `wind_x_coeff`, and `wind_y_coeff` for each distance band, and let the simulation compute flight time internally from the angle/power you are testing.

If you still want an explicit time factor, make it a derived value from the simulation, not a learned constant. For example, compute the flight duration inside `simulate_shot(...)` and then use that result as part of the wind effect:

```python
wind_factor = flight_time
vx += wx * wind_x_coeff * wind_factor
vy += wy * wind_y_coeff * wind_factor
```

But then `flight_time` comes from the model, not from the data directly.

The better calibration setup is:

* fit per-band coefficients first,
* keep `time_scale` fixed to `1.0`,
* only add a time factor later if the model still misses consistently.

So the short answer is: you probably cannot extract a trustworthy standalone `time_scale` from your current data. Treat it as a derived internal value or fold it into the wind coefficients.
