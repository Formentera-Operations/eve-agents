import { defineTool } from "eve/tools";
import { z } from "zod";

const currentWeatherSchema = z.object({
  current: z.object({
    temperature_2m: z.number(),
    wind_speed_10m: z.number(),
    weather_code: z.number(),
  }),
});

// Exported for unit tests: pure parsing stays separate from the fetch.
export function parseCurrentWeather(payload: unknown) {
  const { current } = currentWeatherSchema.parse(payload);
  return {
    temperatureC: current.temperature_2m,
    windSpeedKmh: current.wind_speed_10m,
    weatherCode: current.weather_code,
  };
}

export default defineTool({
  description:
    "Get the current weather (temperature, wind, condition code) for a location given its latitude and longitude.",
  inputSchema: z.object({
    latitude: z.number().min(-90).max(90),
    longitude: z.number().min(-180).max(180),
  }),
  async execute({ latitude, longitude }) {
    const url = new URL("https://api.open-meteo.com/v1/forecast");
    url.searchParams.set("latitude", String(latitude));
    url.searchParams.set("longitude", String(longitude));
    url.searchParams.set("current", "temperature_2m,wind_speed_10m,weather_code");

    const response = await fetch(url);
    if (!response.ok) {
      return { error: `Weather service responded ${response.status}` };
    }
    return parseCurrentWeather(await response.json());
  },
});
