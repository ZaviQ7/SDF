import asyncio
import aiohttp
import traceback

async def test_url(session, url, name):
    print(f"Testing {name} URL: {url}")
    try:
        start_time = asyncio.get_event_loop().time()
        async with session.get(url, timeout=15) as resp:
            elapsed = asyncio.get_event_loop().time() - start_time
            print(f"  Result for {name}: Status {resp.status} in {elapsed:.2f}s")
            if resp.status == 200:
                data = await resp.json()
                print(f"  Success! hourly keys: {list(data.get('hourly', {}).keys())}")
            else:
                text = await resp.text()
                print(f"  Error response: {text[:200]}")
    except Exception as e:
        print(f"  Exception for {name}: {type(e).__name__}: {e}")

async def main():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
    
    # Target coordinate (Philadelphia)
    lat, lon = 39.8722, -75.2408
    timezone = "America/New_York"
    
    urls = {
        "ECMWF": f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=ecmwf_ifs025_ensemble&temperature_unit=fahrenheit&timezone={timezone}",
        "GFS": f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=gfs_seamless&temperature_unit=fahrenheit&timezone={timezone}",
        "ICON": f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=icon_seamless&temperature_unit=fahrenheit&timezone={timezone}",
        "GEM": f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=gem_global&temperature_unit=fahrenheit&timezone={timezone}",
        "HRRR": f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=ncep_hrrr_conus&temperature_unit=fahrenheit&timezone={timezone}&forecast_days=3"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for name, url in urls.items():
            await test_url(session, url, name)
            await asyncio.sleep(1.0) # wait between tests

if __name__ == "__main__":
    asyncio.run(main())
