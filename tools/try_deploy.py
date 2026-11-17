"""Prueba el núcleo de despliegue sin el bot de Telegram.

    TGCLOUD_TOKEN=app…:… python tools/try_deploy.py proyecto.zip            # solo el plan
    TGCLOUD_TOKEN=app…:… python tools/try_deploy.py proyecto.zip --publish  # y publica (migraciones seguras)
Opcional: TGCLOUD_BIN="node /ruta/tgcloud.js" (por defecto «tgcloud»), --destructive para aplicar borrados.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.deploy.cli import Cli  # noqa: E402
from bot.deploy.job import DeployError, Job  # noqa: E402


async def main():
    zip_path = sys.argv[1]
    token = os.environ.pop("TGCLOUD_TOKEN", "")
    job = Job(0, token, tempfile.mkdtemp(prefix="builder-hub-"), Cli(os.environ.get("TGCLOUD_BIN", "tgcloud")))
    try:
        await job.connect()
        print(f"Conectado a {job.app} · revisión {job.revision} · {job.deployed_modules} módulos en la nube")
        plan = await job.load_zip(zip_path)
        r = plan.report
        print(f"Módulos: {len(r.modules)} · web: {r.static_dir} ({r.static_files} archivos) · raíz quitada: {plan.stripped_root}")
        for i in r.issues:
            print(f"  [{i.level}] {i.code} {i.file} {i.detail}")
        if r.errors:
            print(r.for_ai())
            return
        st, sp = plan.status, plan.schema
        print(f"Nuevos {len(st.new)} · cambiados {len(st.modified)} · se borran {len(st.deleted)} · web {len(st.static_lines)} líneas")
        print(f"Tablas: +{len(sp.safe)} · borrados {len(sp.destructive)} · a mano {len(sp.manual)} · fuera del esquema {len(sp.undocumented)} · web sin gestionar: {plan.unmanaged_static}")
        if "--publish" in sys.argv:
            out = await job.publish(allow_destructive="--destructive" in sys.argv)
            print("Publicado" if out.ok else "FALLO", out.static_url, out.migrated, out.webhook, out.error[:300])
    except DeployError as exc:
        print("ERROR", exc.code, exc.detail[:400])
    finally:
        job.cleanup()


asyncio.run(main())
