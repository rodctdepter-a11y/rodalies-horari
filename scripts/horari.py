# -*- coding: utf-8 -*-
"""
Prepara l'horari oficial de Renfe d'avui i de demà, només per a Catalunya, en fitxers JSON petits.

- Rodalies (fitxer de Cercanías de Renfe): rutes dels nuclis 50 i 51.
- Regionals i altres trens (fitxer d'Alta Velocitat, Llarga i Mitjana Distància): viatges amb almenys
  dues parades a Catalunya, desant només les parades de Catalunya.

Surt a horari/AAAA-MM-DD.json, horari/avui.json i horari/dema.json. Esborra els de fa més de 7 dies.
Només fa servir la biblioteca estàndard de Python 3.9+.
"""
import csv, datetime as dt, io, json, os, re, sys, urllib.request, zipfile
from zoneinfo import ZoneInfo

FONTS = {
    "cercanias": "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
    "ld": "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip",
}
BBOX = (40.45, 0.12, 42.9, 3.36)
RX_LINIA = re.compile(r"\b(R(?:G1|T[12]|L[1-4]|1[1-7]|2[NS]|[1-8]))\b")
CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "horari")
UA = "Mozilla/5.0 (X11; Linux x86_64) HorariRodalies/1.0"


def baixa(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def taula(z, nom):
    if nom not in z.namelist():
        return
    with z.open(nom) as fh:
        r = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace"))
        cap = [c.strip() for c in next(r)]
        for fila in r:
            yield {k: (v.strip() if v else "") for k, v in zip(cap, fila)}


def minuts(h):
    try:
        a, b, c = (int(x) for x in h.split(":"))
        return a * 60 + b + (1 if c >= 30 else 0)
    except Exception:
        return None


def serveis(z, d):
    dia = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][d.weekday()]
    ymd = d.strftime("%Y%m%d")
    s = set()
    for c in taula(z, "calendar.txt") or []:
        if c.get(dia) == "1" and c.get("start_date", "") <= ymd <= c.get("end_date", ""):
            s.add(c["service_id"])
    for c in taula(z, "calendar_dates.txt") or []:
        if c.get("date") == ymd:
            (s.add if c.get("exception_type") == "1" else s.discard)(c["service_id"])
    return s


def linia(txt):
    m = RX_LINIA.search(re.sub(r"\s+", "", (txt or "").upper()))
    return m.group(1) if m else ""


def numero(trip, short):
    if short and re.fullmatch(r"\d{3,6}", short):
        return str(int(short))
    m = re.match(r"^\d{4}\w(\d{5})", trip)          # format de Cercanías: servei (5) + tren (5) + línia
    if m:
        return str(int(m.group(1)))
    m = re.search(r"(\d{5})", trip)
    return str(int(m.group(1))) if m else ""


def processa(z, d, font, estacions, viatges):
    srv = serveis(z, d)
    stops = {}
    for s in taula(z, "stops.txt"):
        try:
            la, lo = float(s["stop_lat"]), float(s["stop_lon"])
        except Exception:
            continue
        if BBOX[0] < la < BBOX[2] and BBOX[1] < lo < BBOX[3]:
            nom = re.sub(r"\s*\((apt|apd|apeadero)\)\s*$", "", re.sub(r"^Estaci[oó]n de (tren|Cercan[ií]as)\s*", "", s.get("stop_name", "")), flags=re.I).strip()
            stops[s["stop_id"]] = [nom, round(la, 5), round(lo, 5)]
    rutes = {}
    for r in taula(z, "routes.txt"):
        rid = r["route_id"]
        if font == "cercanias" and rid[:2] not in ("50", "51"):
            continue
        rutes[rid] = (linia(r.get("route_short_name")) or linia(rid[6:] if font == "cercanias" else ""), (r.get("route_short_name") or r.get("route_long_name") or "").strip())
    trips = {}
    for t in taula(z, "trips.txt"):
        if t["route_id"] in rutes and t["service_id"] in srv:
            trips[t["trip_id"]] = (rutes[t["route_id"]], numero(t["trip_id"], t.get("trip_short_name", "")))
    parades = {}
    for s in taula(z, "stop_times.txt"):
        tid = s["trip_id"]
        if tid in trips and s["stop_id"] in stops:
            parades.setdefault(tid, []).append((int(s["stop_sequence"] or 0), s["stop_id"], minuts(s["arrival_time"]), minuts(s["departure_time"])))
    n = 0
    for tid, ps in parades.items():
        if len(ps) < 2:
            continue
        ps.sort()
        (lin, prod), num = trips[tid]
        if font == "ld" and not lin and not prod:
            continue
        viatges.append([tid, num, lin, prod if font == "ld" else "", [[p, a, b] for _, p, a, b in ps]])
        for _, p, _, _ in ps:
            estacions[p] = stops[p]
        n += 1
    return n


def main():
    ara = dt.datetime.now(ZoneInfo("Europe/Madrid"))
    dies = [ara.date(), ara.date() + dt.timedelta(days=1)]
    zips, errors = {}, {}
    for k, u in FONTS.items():
        try:
            zips[k] = zipfile.ZipFile(io.BytesIO(baixa(u)))
            print(f"Descarregat {k}")
        except Exception as e:
            errors[k] = str(e)
            print(f"ERROR {k}: {e}", file=sys.stderr)
    if not zips:
        sys.exit("No s'ha pogut descarregar cap horari")
    os.makedirs(CARPETA, exist_ok=True)
    for i, d in enumerate(dies):
        estacions, viatges, recompte = {}, [], {}
        for k, z in zips.items():
            recompte[k] = processa(z, d, k, estacions, viatges)
        out = {"data": d.isoformat(), "generat": ara.isoformat(timespec="seconds"), "unitat_hores": "minuts des de mitjanit (hora local)",
               "fonts": {k: {"url": FONTS[k], "viatges": recompte.get(k, 0), "error": errors.get(k)} for k in FONTS},
               "estacions": estacions, "viatges": viatges}
        txt = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
        for nom in [f"{d.isoformat()}.json", "avui.json" if i == 0 else "dema.json"]:
            with open(os.path.join(CARPETA, nom), "w", encoding="utf-8") as fh:
                fh.write(txt)
        print(f"{d}: {len(viatges)} viatges, {len(estacions)} estacions, {len(txt)/1e6:.2f} MB")
    limit = (ara.date() - dt.timedelta(days=7)).isoformat()
    for f in os.listdir(CARPETA):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f) and f[:10] < limit:
            os.remove(os.path.join(CARPETA, f))


if __name__ == "__main__":
    main()
