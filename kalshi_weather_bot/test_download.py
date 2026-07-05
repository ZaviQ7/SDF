import asyncio
import aiohttp
import traceback

async def main():
    url = "https://ensemble-api.open-meteo.com/v1/ensemble?latitude=39.8722&longitude=-75.2408&hourly=temperature_2m&models=gfs_seamless&temperature_unit=fahrenheit&timezone=America/New_York"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    print("Testing connection to Open-Meteo ensemble API...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                print(f"Status code: {resp.status}")
                print(f"Headers: {dict(resp.headers)}")
                if resp.status == 200:
                    data = await resp.json()
                    print("Success! Keys in response:", list(data.keys()))
                else:
                    text = await resp.text()
                    print("Error response text:", text[:500])
    except Exception as e:
        print("Exception occurred:")
        print(f"Type: {type(e)}")
        print(f"String representation: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
