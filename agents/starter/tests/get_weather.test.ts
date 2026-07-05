import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import getWeather, { parseCurrentWeather } from "../agent/tools/get_weather.ts";

const fixture = {
  current: { temperature_2m: 21.4, wind_speed_10m: 9.7, weather_code: 3 },
};

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("parseCurrentWeather maps the Open-Meteo payload", () => {
  assert.deepEqual(parseCurrentWeather(fixture), {
    temperatureC: 21.4,
    windSpeedKmh: 9.7,
    weatherCode: 3,
  });
});

test("parseCurrentWeather rejects a malformed payload", () => {
  assert.throws(() => parseCurrentWeather({ current: {} }));
});

test("execute fetches and returns parsed weather", async () => {
  globalThis.fetch = async () => Response.json(fixture);
  const result = await getWeather.execute(
    { latitude: 40.69, longitude: -73.99 },
    {} as never,
  );
  assert.deepEqual(result, {
    temperatureC: 21.4,
    windSpeedKmh: 9.7,
    weatherCode: 3,
  });
});

test("execute surfaces an upstream error status", async () => {
  globalThis.fetch = async () => new Response("nope", { status: 503 });
  const result = await getWeather.execute(
    { latitude: 40.69, longitude: -73.99 },
    {} as never,
  );
  assert.deepEqual(result, { error: "Weather service responded 503" });
});
