#!/usr/bin/env python3
"""Actualiza exclusivamente datos ZC. No carga app.py ni el monitor de avisos."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import requests

import meteorologia_compartida as met
import red_integrada as red

REPOSITORY = "FedericoIeraci-cell/alerta-zarate-campana"
STATE_BRANCH = "zc-datos-state"
STATUS_PATH = "datos_status.json"
ALLOWED_FILES = {red.SNAPSHOT_PATH, met.SNAPSHOT_ZC_PATH, STATUS_PATH}


class PublicacionError(RuntimeError):
    """Diagnóstico acotado, sin respuestas HTTP ni credenciales."""


class GitHubPublicador:
    """Una sola confirmación atómica de informe, estado y captura disponible."""

    def __init__(self, token, repository=REPOSITORY, session=None):
        if repository != REPOSITORY:
            raise PublicacionError("El publicador ZC sólo puede escribir en su propio repositorio.")
        if not isinstance(token, str) or not token.strip():
            raise PublicacionError("Falta la credencial del publicador de datos ZC.")
        self.repository = repository
        self.session = session or requests.Session()
        self.headers = {"Authorization": "Bearer " + token.strip(),
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "Cache-Control": "no-cache"}

    def _request(self, method, endpoint, *, missing=False, **kwargs):
        try:
            response = self.session.request(
                method, "https://api.github.com/repos/" + self.repository + endpoint,
                headers=self.headers, timeout=(5, 30), allow_redirects=False, **kwargs)
            if missing and response.status_code == 404:
                return None
            if not 200 <= response.status_code < 300:
                raise PublicacionError(f"GitHub no confirmó los datos ZC (HTTP {response.status_code}).")
            data = response.json()
            if not isinstance(data, dict):
                raise PublicacionError("GitHub devolvió una confirmación incompatible.")
            return data
        except PublicacionError:
            raise
        except Exception:
            raise PublicacionError("No se pudo confirmar la publicación de datos ZC.") from None
        finally:
            if 'response' in locals():
                response.close()

    @staticmethod
    def _sha(value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise PublicacionError("GitHub no identificó el contenido publicado.")
        return value

    def _head(self, *, missing=False):
        data = self._request("GET", "/git/ref/heads/" + STATE_BRANCH, missing=missing)
        return None if data is None else self._sha(data.get("object", {}).get("sha"))

    def publicar(self, archivos):
        if (not isinstance(archivos, dict) or not {red.SNAPSHOT_PATH, STATUS_PATH} <= archivos.keys()
                or set(archivos) - ALLOWED_FILES):
            raise PublicacionError("El conjunto de archivos ZC no es válido.")
        for nombre, contenido in archivos.items():
            if not isinstance(contenido, bytes) or not 0 < len(contenido) <= red.MAX_BYTES:
                raise PublicacionError("Un archivo de datos ZC excede el límite permitido.")
        informe = red.validar_red_integrada(json.loads(archivos[red.SNAPSHOT_PATH]))
        if informe.get("regiones") != ["Zárate–Campana"] or not informe["snapshot_vigente"]:
            raise PublicacionError("El informe no corresponde a una consulta vigente de ZC.")
        red._registro_publico_monitor(json.loads(archivos[STATUS_PATH]))
        if met.SNAPSHOT_ZC_PATH in archivos:
            met.deserializar_captura(archivos[met.SNAPSHOT_ZC_PATH], red.NODOS_ZC)
        head = self._head(missing=True)
        if head is None:
            metadata = self._request("GET", "")
            branch = metadata.get("default_branch")
            if not isinstance(branch, str) or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
                raise PublicacionError("No se pudo identificar la rama de código ZC.")
            base = self._request("GET", "/git/ref/heads/" + branch)
            head = self._sha(base.get("object", {}).get("sha"))
            self._request("POST", "/git/refs", json={"ref": "refs/heads/" + STATE_BRANCH, "sha": head})
        parent = self._request("GET", "/git/commits/" + head)
        tree = self._sha(parent.get("tree", {}).get("sha"))
        entries = []
        for nombre, contenido in archivos.items():
            expected = hashlib.sha1(b"blob " + str(len(contenido)).encode("ascii") + b"\0" + contenido).hexdigest()
            blob = self._request("POST", "/git/blobs", json={
                "content": base64.b64encode(contenido).decode("ascii"), "encoding": "base64"})
            if self._sha(blob.get("sha")) != expected:
                raise PublicacionError("El contenido confirmado no coincide con los datos ZC.")
            entries.append({"path": nombre, "mode": "100644", "type": "blob", "sha": expected})
        built = self._request("POST", "/git/trees", json={"base_tree": tree, "tree": entries})
        tree_sha = self._sha(built.get("sha"))
        commit = self._request("POST", "/git/commits", json={
            "message": "ZC: actualizar datos locales independientes", "tree": tree_sha, "parents": [head]})
        sha = self._sha(commit.get("sha"))
        # force=false rechaza una escritura concurrente; nunca reemplaza una rama desconocida.
        self._request("PATCH", "/git/refs/heads/" + STATE_BRANCH, json={"sha": sha, "force": False})
        if self._head() != sha:
            raise PublicacionError("La rama ZC cambió durante la confirmación.")
        confirmed = self._request("GET", "/git/trees/" + tree_sha)
        found = {item.get("path"): item.get("sha") for item in confirmed.get("tree", [])}
        if confirmed.get("truncated") or any(found.get(item["path"]) != item["sha"] for item in entries):
            raise PublicacionError("No se confirmó el conjunto completo de archivos ZC.")
        return {"commit_sha": sha, "verified_at": datetime.now(timezone.utc).isoformat(),
                "archivos": sorted(archivos)}


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"


def ejecutar(*, dry_run=True, publicador=None):
    inicio = datetime.now(timezone.utc)
    errores = []
    captura = None
    # La hidrometría no espera ni depende de que termine la descarga meteorológica.
    with ThreadPoolExecutor(max_workers=2) as pool:
        meteo = pool.submit(met.crear_captura_zc, referencia=inicio)
        hidro = pool.submit(red.consultar_zc_red, referencia=inicio, meteorologia=[])
        try:
            captura = met.validar_captura(meteo.result(), red.NODOS_ZC)
            if not all(met._con_datos(dato) for dato in captura["datos"]):
                raise met.CapturaMeteorologicaError("La captura completa no cubre las diez referencias ZC.")
        except Exception as error:
            captura = None
            errores.append(str(error) if isinstance(error, met.CapturaMeteorologicaError)
                           else "No se confirmó la captura meteorológica completa de ZC.")
        try:
            zc = hidro.result()
        except Exception:
            zc = {"nodos": [], "rios": [], "fuentes": []}
            errores.append("No se confirmó la consulta hidrométrica de ZC.")
    if captura is not None:
        nodos = []
        for nodo, dato in zip(red.NODOS_ZC, captura["datos"]):
            fila = red.parsear_meteorologia_zc(nodo, dato, captura["consultado"])
            fila.update(recuperacion="CONSULTA_DIRECTA", fecha_ultimo_intento=captura["consultado"])
            nodos.append(red._guardar_grilla_zc(fila, dato))
    else:
        previo = red.consultar_red_integrada(actualizar=True)
        nodos = red.consultar_meteorologia_zc(anterior=previo)
    zc["nodos"] = nodos
    # La consulta hidrométrica se hizo sin meteorología. Su fila provisional
    # 0/10 se reemplaza por el resultado real de la descarga independiente.
    zc["fuentes"] = [f for f in zc["fuentes"] if f.get("organismo") != "Open-Meteo / ECMWF"]
    zc["fuentes"].append({"red": "Zárate–Campana", "organismo": "Open-Meteo / ECMWF",
        "url": met.FUENTE, "consultado": inicio.isoformat(), "fecha_documento": None,
        "error": errores[0] if captura is None else ""})
    ahora = datetime.now(timezone.utc)
    documento = red.construir_red_integrada([], {}, zc=zc, referencia=ahora, region="Zárate–Campana")
    validos = sum(n.get("vigente") is True and n.get("lluvia_prevista_72_mm") is not None for n in documento["nodos"])
    rios = documento["rios"]
    previstos = [r for r in rios if r.get("serie_pronostico") is not None]
    cobertura = {
        "meteorologia": {"vigentes": validos, "aplicables": len(red.NODOS_ZC)},
        "meteorologia_completa": {"vigentes": len(red.NODOS_ZC) if captura is not None else 0, "aplicables": len(red.NODOS_ZC)},
        "hidrologia_observada": {"vigentes": sum(r.get("observacion_vigente") is True for r in rios), "aplicables": 3},
        "hidrologia_prevista": {"vigentes": sum(r.get("pronostico_vigente") is True for r in previstos), "aplicables": 2},
    }
    parcial = any(c["vigentes"] < c["aplicables"] for c in cobertura.values())
    estado = {"schema_version": 1, "checked_at": ahora.isoformat(), "frequency_minutes": 10,
        "scope": red.ALCANCE_DATOS_ZC, "health": "error_meteorologia" if errores else "datos_parciales" if parcial else "ok",
        "dry_run": dry_run, "publication_only": True, "red_integrada_publicada": not dry_run,
        "red_integrada_estado": "no_solicitada" if dry_run else "publicada",
        "nodes_total": len(red.NODOS_ZC), "nodes_valid": validos, "nodes_red": 0,
        "coverage": cobertura, "errors": errores, "envia_telegram": False,
        "meteorologia_completa_publicada": captura is not None and not dry_run}
    documento["monitor"] = {k: estado[k] for k in ("checked_at", "health", "scope", "frequency_minutes", "dry_run", "nodes_total", "nodes_valid", "nodes_red")}
    archivos = {red.SNAPSHOT_PATH: _bytes(documento), STATUS_PATH: _bytes(estado)}
    if captura is not None:
        archivos[met.SNAPSHOT_ZC_PATH] = met.serializar_captura(captura)
    if not dry_run:
        publicador = publicador or GitHubPublicador(os.environ.get("GITHUB_TOKEN", ""),
                                                   os.environ.get("GITHUB_REPOSITORY", ""))
        estado["confirmacion"] = publicador.publicar(archivos)
    return estado, documento


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modos = parser.add_mutually_exclusive_group(required=True)
    modos.add_argument("--dry-run", action="store_true")
    modos.add_argument("--publicar", action="store_true")
    parser.add_argument("--export-red")
    args = parser.parse_args(argv)
    try:
        estado, documento = ejecutar(dry_run=not args.publicar)
        if args.export_red:
            Path(args.export_red).write_bytes(_bytes(documento))
        print(json.dumps(estado, ensure_ascii=False, allow_nan=False))
        return 1 if estado["errors"] else 0
    except Exception as error:
        mensaje = str(error) if isinstance(error, PublicacionError) else "No se completó la actualización independiente de datos ZC."
        print(mensaje)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
