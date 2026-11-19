"""Genera las imágenes de la marca. Uso (imagen de Playwright): python render.py /marca"""
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
D = Path(sys.argv[1])
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 640, "height": 640})
        await pg.goto((D / "profile.html").as_uri())
        await pg.wait_for_timeout(200)
        await pg.screenshot(path=str(D / "profile.jpg"), type="jpeg", quality=92)
        await pg.screenshot(path=str(D / "logo-640.png"))
        await pg.set_viewport_size({"width": 560, "height": 208}); await pg.goto((D / "circulo.html").as_uri()); await pg.wait_for_timeout(300)
        await pg.screenshot(path=str(D / "logo-circulo.png"))
        for lang in ("es", "en"):
            pg2 = await b.new_page(viewport={"width": 640, "height": 360})
            await pg2.goto((D / f"banner-{lang}.html").as_uri()); await pg2.wait_for_timeout(1500)
            await pg2.screenshot(path=str(D / f"banner-{lang}-640x360.png"))
        await b.close()
asyncio.run(main())
