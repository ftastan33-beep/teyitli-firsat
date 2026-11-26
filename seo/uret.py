#!/usr/bin/env python3
"""Düşero SEO üreticisi.

veri.json'dan Google'ın JavaScript çalıştırmadan okuyabileceği statik sayfalar üretir:
  /indirimler/                      tüm kategori ve mağazaların merkezi
  /indirimler/<kategori-veya-magaza>/
  /kacirilmaz-firsatlar/  /cok-satanlar/
  sitemap.xml  robots.txt
Ayrıca index.html ve yasal.html'e canonical, Open Graph ve yapılandırılmış veri ekler
(işaretli bloklar her çalışmada yeniden yazılır; site tasarımı güncellense de kaybolmaz).

Yalnızca Python standart kütüphanesi kullanır. Kullanım: python3 seo/uret.py [site_dizini]
GitHub Actions'ta saatte bir çalışır; ileride VDS'e geçildiğinde cron ile aynı şekilde çalıştırılabilir.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

SITE = "https://dusero.com"
AD = "Düşero"
TELEGRAM = "https://t.me/dusero_tr"
KAPAK = f"{SITE}/paylasim.jpg"
TR = timezone(timedelta(hours=3))
_ARG = [a for a in sys.argv[1:] if not a.startswith("--")]
KOK = os.path.abspath(_ARG[0] if _ARG else os.path.join(os.path.dirname(__file__), ".."))
SAYFA_URUN = 60          # bir sayfada gösterilecek ürün sayısı
MAGAZA_ESIK = 10         # bu sayıdan az ürünü olan mağazaya ayrı sayfa açılmaz
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
         "Eylül", "Ekim", "Kasım", "Aralık"]

# Kategoriye özgü kısa tanıtımlar (Google'ın sayfayı ayırt etmesi için her sayfada farklı metin)
KAT_METIN = {
    "elektronik": "Akıllı telefon, televizyon, kulaklık, akıllı saat ve diğer elektronik ürünlerde fiyatı gerçekten düşenler.",
    "bilgisayar": "Dizüstü bilgisayar, monitör, ekran kartı, SSD, oyun konsolu ve aksesuarlarda gerçek fiyat düşüşleri.",
    "beyaz": "Buzdolabı, çamaşır ve bulaşık makinesi, süpürge, airfryer ve küçük ev aletlerinde gerçek indirimler.",
    "kozmetik": "Parfüm, cilt bakımı, makyaj, saç bakımı ve tıraş ürünlerinde fiyatı gerçekten düşenler.",
    "giyim": "Ayakkabı, mont, sweatshirt, çanta ve aksesuarlarda fiyatı gerçekten düşen ürünler.",
    "gida": "Kahve, çay, atıştırmalık, temel gıda ve içeceklerde fiyatı gerçekten düşenler.",
    "ev": "Mutfak gereçleri, tencere ve tava setleri, ev tekstili, dekorasyon ve mobilyada gerçek indirimler.",
    "bebek": "Bebek bezi, mama, bebek bakım ürünleri ve oyuncaklarda fiyatı gerçekten düşenler.",
    "evcil": "Kedi ve köpek maması, kum ve evcil hayvan ürünlerinde gerçek fiyat düşüşleri.",
    "temizlik": "Deterjan, yumuşatıcı, tuvalet kâğıdı, kâğıt havlu ve temizlik ürünlerinde gerçek indirimler.",
    "yapi": "Matkap, el aletleri, bahçe ürünleri ve yapı market ürünlerinde fiyatı gerçekten düşenler.",
    "oto": "Oto aksesuar, lastik, bakım ürünleri, motosiklet ve elektrikli scooterlarda gerçek indirimler.",
    "spor": "Spor ekipmanı, kamp ve outdoor ürünlerinde fiyatı gerçekten düşenler.",
}
ATLANAN_KATEGORI = {"diger"}


# ---------- yardımcılar ----------
def e(s):
    return html.escape(str(s or ""), quote=True)


def kucuk(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower()


def slug(s):
    s = kucuk(s)
    for a, b in (("ç", "c"), ("ğ", "g"), ("ı", "i"), ("ö", "o"), ("ş", "s"), ("ü", "u"), ("â", "a"), ("î", "i"), ("û", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "diger"


def buyuk_bas(k):
    if not k:
        return k
    ilk = {"i": "İ", "ı": "I"}.get(k[0], k[0].upper())
    return ilk + k[1:]


def baslik_hali(s):
    return " ".join(w if (w.isupper() or w == "&" or not w[0].isalpha()) else buyuk_bas(w) for w in (s or "").split())


def tl(x):
    if x is None:
        return ""
    if abs(x - round(x)) < 0.005:
        return f"{int(round(x)):,}".replace(",", ".") + " TL"
    t = f"{x:,.2f}"
    return t.replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def tarih_yazi(ts):
    d = datetime.fromtimestamp(ts, TR)
    return f"{d.day} {AYLAR[d.month - 1]} {d.year} {d:%H:%M}"


def iso(ts):
    return datetime.fromtimestamp(ts, TR).isoformat(timespec="seconds")


# Uygulamadaki (app.js) indirim hesabının aynısı
GUN = 86400
REF_GUN = 10      # indirimden önceki fiyat: son 10 günün en düşük fiyatı (sitedeki app.js ile aynı kural)
MIN_ROZET = 5
KAC_ESIK = 10


def gercek_indirim(u):
    """Yalnızca Düşero'nun kendi fiyat geçmişinden: mevcut fiyattan önceki 10 günün en düşük fiyatına göre."""
    f = u.get("fiyat") or 0
    if u.get("karar") == "sisirilmis" or f <= 0:
        return None
    g = sorted((p for p in (u.get("gecmis") or []) if p and len(p) > 1 and (p[1] or 0) > 0), key=lambda p: p[0])
    if len(g) < 2:
        return None
    bas = max(u.get("teyit") or 0, g[-1][0])
    for ts, fy in reversed(g):
        if fy <= f * 1.005:
            bas = ts
        else:
            break
    pb = bas - REF_GUN * GUN
    if g[0][0] > pb:
        return None
    ilk = None
    for ts, fy in g:
        if ts <= pb:
            ilk = fy
        else:
            break
    fl = [x for x in [ilk] + [fy for ts, fy in g if pb < ts < bas] if x and x > 0]
    if not fl:
        return None
    ref = min(fl)
    if ref <= f:
        return None
    o = round((ref - f) / ref * 100)
    return {"oran": o, "tl": ref - f, "ref": ref} if o >= MIN_ROZET else None


def normallestir(u):
    """Mağazanın üstü çizili fiyatı ve başka kanalların oranı indirim olarak kullanılmaz."""
    g = gercek_indirim(u)
    u["_g"] = g
    u["yuzde"] = g["oran"] if g else None
    u["eski_fiyat"] = g["ref"] if g else None
    ak = u.get("akakce") or {}
    ucuz = bool(ak.get("en_ucuz") and u["fiyat"] > ak["en_ucuz"] * 1.05)
    u["kac"] = bool(g and g["oran"] >= KAC_ESIK and not ucuz)


def indirim(u):
    return u.get("_g")


def oran(u):
    i = indirim(u)
    return i["oran"] if i else 0


def sirala(ls):
    def anahtar(u):
        i = indirim(u)
        return (-oran(u), -(i["tl"] if i else 0), -(u.get("ilk") or 0))
    return sorted(ls, key=anahtar)


ETIKET = {
    "dip": ("Gerçek indirim", "k-dip"),
    "iyi": ("İyi fiyat", "k-iyi"),
}


# ---------- sayfa parçaları ----------
def kart(u):
    i = indirim(u)
    o = oran(u)
    resim = u.get("resim")
    gorsel = (f'<img src="{e(resim)}" alt="{e(u["baslik"])}" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
              if resim else "")
    rozet = f'<span class="oran-rozet">%{o}</span>' if i and o > 0 else ""
    eski = f'<s class="eski">{tl(i["ref"])}</s>' if i else ""
    etk = ""
    if u.get("kac"):
        etk = '<span class="etk k-kac">Kaçırılmaz</span>'
    elif u.get("karar") in ETIKET:
        ad, sinif = ETIKET[u["karar"]]
        etk = f'<span class="etk {sinif}">{ad}</span>'
    not_ = ""
    if u.get("dip"):
        not_ = f'<span class="kosul">{e(u["dip"])}</span>'
    elif u.get("cok"):
        c = u["cok"]
        not_ = f'<span class="cok">{e(c.get("m"))} {e(c.get("k"))} kategorisinde {e(c.get("s"))}. en çok satan</span>'
    return (
        '<article class="kart">'
        f'<a class="kart-link" href="/#u-{e(u["id"])}">'
        f'<div class="gorsel{"" if resim else " yok"}">{rozet}{gorsel}</div>'
        '<div class="govde">'
        f'<span class="magaza">{e(u.get("magaza_ad"))}</span>'
        f'<h3 class="baslik">{e(u["baslik"])}</h3>'
        f'{eski}<span class="fiyat-satir"><span class="fiyat">{tl(u.get("fiyat"))}</span></span>'
        f'{etk}{not_}'
        '</div></a></article>'
    )


EK_STIL = """<style>
.seo-yol{font-size:13px;color:var(--soluk);margin:14px 0 4px}.seo-yol a{color:inherit}
.seo-giris{max-width:760px;color:var(--gri-yazi);line-height:1.55;margin:6px 0 4px}
.seo-zaman{font-size:13px;color:var(--soluk);margin:0 0 14px}
.seo-linkler{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 18px;padding:0;list-style:none}
.seo-linkler a{display:inline-block;padding:7px 12px;border:1px solid var(--cizgi-koyu);border-radius:999px;background:var(--kart);color:var(--murekkep);text-decoration:none;font-size:14px;font-weight:600}
.seo-linkler a[aria-current]{background:var(--vurgu);border-color:var(--vurgu);color:#fff}
.seo-blok{margin:26px 0 8px}.seo-blok h2{font-size:18px;margin:0 0 6px}.seo-blok p{color:var(--gri-yazi);line-height:1.55;max-width:760px}
.seo-tumu{margin:18px 0 6px;text-align:center}
.kart .kosul,.kart .cok,.kart .etk{display:inline-block}
@media (max-width:719px){body.seo-sayfa{padding-bottom:0}}
</style>"""


def link_listesi(sayfalar, aktif=None):
    li = []
    for s in sayfalar:
        cur = ' aria-current="page"' if s["yol"] == aktif else ""
        li.append(f'<li><a href="{s["yol"]}"{cur}>{e(s["kisa"])}</a></li>')
    return '<ul class="seo-linkler">' + "".join(li) + "</ul>"


def sayfa_html(s, tum_kat, tum_mag, guncelleme, v):
    yol, url = s["yol"], SITE + s["yol"]
    kirinti = [("Ana sayfa", "/")] + s.get("ust", []) + [(s["kisa"], yol)]
    ld = [
        {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": ad, "item": SITE + y}
                                for i, (ad, y) in enumerate(kirinti)],
        },
        {
            "@context": "https://schema.org", "@type": "CollectionPage",
            "name": s["h1"], "description": s["aciklama"], "url": url, "inLanguage": "tr-TR",
            "dateModified": iso(guncelleme),
            "isPartOf": {"@type": "WebSite", "name": AD, "url": SITE + "/"},
        },
    ]
    yol_html = " › ".join(f'<a href="{y}">{e(ad)}</a>' if y != yol else e(ad) for ad, y in kirinti)
    kartlar = "".join(kart(u) for u in s["urunler"][:SAYFA_URUN])
    bos = '<p class="durum">Şu anda bu bölümde yayında ürün yok; liste gün içinde güncellenir.</p>' if not s["urunler"] else ""
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(s["title"])}</title>
<meta name="description" content="{e(s["aciklama"])}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#22307a">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{AD}">
<meta property="og:locale" content="tr_TR">
<meta property="og:title" content="{e(s["title"])}">
<meta property="og:description" content="{e(s["aciklama"])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{KAPAK}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/ikon-192.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="stylesheet" href="/stil.css?v={e(v)}">
{EK_STIL}
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head>
<body class="seo-sayfa">
<header class="ust">
<div class="kap ust-ic">
<a class="marka" href="/" aria-label="{AD} ana sayfa"><img class="logo-resim" src="/logo-koyu.png?v={e(v)}" width="400" height="149" alt="{AD}"></a>
<a class="dugme ikincil" href="/">Tüm fırsatlar</a>
</div>
</header>
<main class="kap">
<nav class="seo-yol" aria-label="Sayfa yolu">{yol_html}</nav>
<h1>{e(s["h1"])}</h1>
<p class="seo-giris">{e(s["giris"])}</p>
<p class="seo-zaman">Son güncelleme: {tarih_yazi(guncelleme)} · {len(s["urunler"])} ürün</p>
{bos}<div class="izgara">{kartlar}</div>
<p class="seo-tumu"><a class="dugme turuncu" href="/">Tüm fırsatları ve fiyat geçmişlerini gör</a></p>
<section class="seo-blok">
<h2>Kategoriye göre indirimler</h2>
{link_listesi(tum_kat, yol)}
<h2>Mağazaya göre indirimler</h2>
{link_listesi(tum_mag, yol)}
</section>
<section class="seo-blok">
<h2>Düşero indirimleri nasıl kontrol ediyor?</h2>
<p>Her ürünün fiyatı ve stoğu mağaza sayfasından okunur; indirim oranı mağazanın üstü çizili fiyatından değil, ürünün son 10 günde kaydettiğimiz en düşük fiyatından hesaplanır; fiyat geçmişi 10 günden kısa olan üründe oran gösterilmez. Bu fiyattan en az %10 ucuza inen ürünler “Kaçırılmaz”, dönemin en düşük fiyatındakiler “Gerçek indirim”, olağan fiyatının altındakiler “İyi fiyat” olarak işaretlenir. Önce fiyatı artırılıp sonra “indirim” diye sunulan ürünler bu etiketleri almaz. Fiyatlar mağazalarca anlık değişebilir; satın almadan önce mağazadaki son fiyatı kontrol edin.</p>
<p>Fiyat düştüğü anda haber almak için <a href="{TELEGRAM}" rel="noopener">Düşero Telegram kanalına</a> katılabilirsiniz.</p>
</section>
</main>
<footer class="alt">
<div class="kap alt-ic">
<div><span class="marka-ad">{AD}</span>
<p>{AD} bağımsız bir fiyat takip sitesidir; satış yapmaz. Sitedeki bazı bağlantılar satış ortaklığı (reklam) bağlantısıdır; bu bağlantılardan alışveriş yaptığınızda {AD} komisyon kazanabilir, ödediğiniz fiyat değişmez.</p></div>
<nav aria-label="Yasal" class="alt-menu"><a href="/yasal.html">Yasal bilgiler</a> <a href="/yasal.html#kvkk">Kişisel veriler</a> <a href="/yasal.html#iletisim">İletişim</a></nav>
</div>
<p class="kap telif">© {datetime.now(TR).year} {AD}</p>
</footer>
</body>
</html>
"""


# ---------- index.html / yasal.html'e eklenecek bloklar ----------
BAS_ISARET, SON_ISARET = "<!--seo:bas-->", "<!--seo:son-->"
LBAS, LSON = "<!--seo-linkler:bas-->", "<!--seo-linkler:son-->"
ANA_TITLE = "Düşero · Fiyatı Gerçekten Düşen Ürünler ve Gerçek İndirimler"
ANA_ACIKLAMA = ("Trendyol, Hepsiburada, Amazon ve n11'de fiyatı gerçekten düşen ürünler. İndirim oranı, ürünün son 10 "
                "gündeki en düşük fiyatına göre hesaplanır.")


def blok_degistir(metin, bas, son, yeni, once):
    """bas..son arası bloğu yeniler; yoksa `once` dizesinden hemen önce ekler."""
    desen = re.compile(re.escape(bas) + r".*?" + re.escape(son), re.S)
    parca = bas + yeni + son
    if desen.search(metin):
        return desen.sub(lambda _: parca, metin, count=1)
    i = metin.find(once)
    return metin if i < 0 else metin[:i] + parca + " " + metin[i:]


def ana_sayfa_isle(tum_kat, tum_mag):
    yol = os.path.join(KOK, "index.html")
    if not os.path.exists(yol):
        return
    m = open(yol, encoding="utf-8").read()
    ilk = m
    m = re.sub(r"<title>.*?</title>", f"<title>{e(ANA_TITLE)}</title>", m, count=1, flags=re.S)
    m = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{e(ANA_ACIKLAMA)}">', m, count=1)
    m = re.sub(r'<meta property="og:image" content="[^"]*">\s*', "", m)  # göreli og:image yerine mutlak olan eklenir
    ld = [
        {"@context": "https://schema.org", "@type": "Organization", "@id": SITE + "/#org", "name": AD,
         "url": SITE + "/", "logo": SITE + "/ikon-512.png", "sameAs": [TELEGRAM]},
        {"@context": "https://schema.org", "@type": "WebSite", "@id": SITE + "/#site", "name": AD,
         "alternateName": ["Dusero", "Düşero Fırsat"], "url": SITE + "/", "inLanguage": "tr-TR",
         "publisher": {"@id": SITE + "/#org"}},
    ]
    bas = (f'<link rel="canonical" href="{SITE}/"> <meta name="robots" content="index, follow, max-image-preview:large"> '
           f'<meta property="og:type" content="website"> <meta property="og:site_name" content="{AD}"> '
           f'<meta property="og:locale" content="tr_TR"> <meta property="og:url" content="{SITE}/"> '
           f'<meta property="og:image" content="{KAPAK}"> <meta property="og:image:width" content="1200"> '
           f'<meta property="og:image:height" content="630"> <meta name="twitter:card" content="summary_large_image"> '
           f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>')
    m = blok_degistir(m, BAS_ISARET, SON_ISARET, bas, "</head>")
    linkler = ('<section class="bolum seo-blok" aria-labelledby="seo-kat-baslik">'
               '<style>.seo-linkler{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 16px;padding:0;list-style:none}'
               '.seo-linkler a{display:inline-block;padding:7px 12px;border:1px solid var(--cizgi-koyu);border-radius:999px;'
               'background:var(--kart);color:var(--murekkep);text-decoration:none;font-size:14px;font-weight:600}'
               '.seo-blok h2{font-size:18px;margin:0 0 4px}</style>'
               '<h2 id="seo-kat-baslik">Kategoriye göre indirimler</h2>' + link_listesi(tum_kat) +
               '<h2>Mağazaya göre indirimler</h2>' + link_listesi(tum_mag) + "</section>")
    m = blok_degistir(m, LBAS, LSON, linkler, "</main>")
    if m != ilk:
        open(yol, "w", encoding="utf-8").write(m)


def yasal_isle():
    yol = os.path.join(KOK, "yasal.html")
    if not os.path.exists(yol):
        return
    m = open(yol, encoding="utf-8").read()
    bas = (f'<link rel="canonical" href="{SITE}/yasal.html"> '
           '<meta name="description" content="Düşero yasal bilgiler, kişisel verilerin korunması (KVKK), '
           'satış ortaklığı bağlantıları ve iletişim bilgileri.">')
    yeni = blok_degistir(m, BAS_ISARET, SON_ISARET, bas, "</head>")
    if yeni != m:
        open(yol, "w", encoding="utf-8").write(yeni)


# ---------- ana akış ----------
def surum():
    try:
        m = open(os.path.join(KOK, "index.html"), encoding="utf-8").read()
        r = re.search(r"stil\.css\?v=([\w.\-]+)", m)
        return r.group(1) if r else "1"
    except OSError:
        return "1"


def yaz(yol, icerik):
    tam = os.path.join(KOK, yol.strip("/"), "index.html") if yol.endswith("/") else os.path.join(KOK, yol.strip("/"))
    os.makedirs(os.path.dirname(tam), exist_ok=True)
    if os.path.exists(tam) and open(tam, encoding="utf-8").read() == icerik:
        return
    with open(tam, "w", encoding="utf-8") as f:
        f.write(icerik)


def veri_oku():
    """veri.json + parça dosyaları (veri-1.json, veri-2.json …) — app.js ile aynı düzen."""
    veri = json.load(open(os.path.join(KOK, "veri.json"), encoding="utf-8"))
    hepsi = list(veri.get("urunler") or [])
    parcalar = veri.get("parcalar")
    adet = len(parcalar) if isinstance(parcalar, list) else int(parcalar or 0)
    for i in range(1, adet + 1):
        yol = os.path.join(KOK, f"veri-{i}.json")
        if not os.path.exists(yol):
            continue
        p = json.load(open(yol, encoding="utf-8"))
        hepsi.extend(p if isinstance(p, list) else (p.get("urunler") or []))
    gor, tekil = set(), []
    for u in hepsi:
        if u.get("id") in gor:
            continue
        gor.add(u.get("id"))
        tekil.append(u)
    return veri, tekil


URETICI = hashlib.sha1(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:12]


def gerek_yok():
    """Ana sayfada SEO bloğu duruyor ve sitemap son 55 dakikada yenilendiyse çalışmaya gerek yok."""
    try:
        ana = open(os.path.join(KOK, "index.html"), encoding="utf-8").read()
        sm = open(os.path.join(KOK, "sitemap.xml"), encoding="utf-8").read()
        if f"<!-- uretici:{URETICI} -->" not in sm:      # üretici kodu değiştiyse her zaman yeniden üret
            return False
        r = re.search(r"<lastmod>([^<]+)</lastmod>", sm)
        son = datetime.fromisoformat(r.group(1)).timestamp() if r else 0
    except (OSError, ValueError):
        return False
    return BAS_ISARET in ana and LBAS in ana and time.time() - son < 55 * 60


def main():
    if "--gerekirse" in sys.argv and gerek_yok():
        print("SEO · güncel, atlandı")
        return
    veri, ham = veri_oku()
    guncelleme = int(veri.get("guncelleme") or time.time())
    urunler = [u for u in ham if (u.get("fiyat") or 0) > 0 and u.get("id") and u.get("baslik")]
    for u in urunler:
        normallestir(u)
    v = surum()
    ay = f"{AYLAR[datetime.fromtimestamp(guncelleme, TR).month - 1]} {datetime.fromtimestamp(guncelleme, TR).year}"

    def ozet(ls):
        en = sirala(ls)[0] if ls else None
        o = oran(en) if en else 0
        return en, o

    sayfalar = []

    # kategoriler
    katlar = {}
    for u in urunler:
        k = u.get("kategori") or "diger"
        if k in ATLANAN_KATEGORI:
            continue
        katlar.setdefault(k, {"ad": u.get("kategori_ad") or k, "ls": []})["ls"].append(u)
    kat_sayfa = []
    for k, d in sorted(katlar.items(), key=lambda x: -len(x[1]["ls"])):
        ad = baslik_hali(d["ad"])
        ls = sirala(d["ls"])
        en, o = ozet(ls)
        giris = KAT_METIN.get(k, f"{ad} kategorisinde fiyatı gerçekten düşen ürünler.") + \
            f" Şu anda {len(ls)} üründe fiyat düşüşü takip ediliyor" + \
            (f"; en büyük düşüş %{o} ile {en['baslik'][:70]}." if en and o > 0 else ".") + \
            " İndirim oranı, ürünün son 10 gündeki en düşük fiyatına göre hesaplanır."
        kat_sayfa.append({
            "yol": f"/indirimler/{slug(d['ad'])}/", "kisa": ad, "h1": f"{ad} İndirimleri",
            "title": f"{ad} İndirimleri – {ay} | {AD}",
            "aciklama": (f"{ad}: fiyatı düşen {len(ls)} ürün" + (f", en büyük düşüş %{o}" if o > 0 else "") +
                         ". İndirim oranı son 10 günün en düşük fiyatına göre hesaplanır, fiyat mağazada kontrol edilir."),
            "giris": giris, "urunler": ls, "ust": [("İndirimler", "/indirimler/")],
        })

    # mağazalar
    magazalar = {}
    for u in urunler:
        ad = u.get("magaza_ad") or u.get("magaza")
        if ad:
            magazalar.setdefault(ad, []).append(u)
    mag_sayfa = []
    for ad, ls in sorted(magazalar.items(), key=lambda x: -len(x[1])):
        if len(ls) < MAGAZA_ESIK:
            continue
        ls = sirala(ls)
        en, o = ozet(ls)
        mag_sayfa.append({
            "yol": f"/indirimler/{slug(ad)}/", "kisa": ad, "h1": f"{ad} İndirimleri ve Fırsatları",
            "title": f"{ad} İndirimleri – Fiyatı Düşenler, {ay} | {AD}",
            "aciklama": (f"{ad} indirimleri: fiyatı düşen {len(ls)} ürün" + (f", en büyük düşüş %{o}" if o > 0 else "") +
                         ". İndirim oranı son 10 günün en düşük fiyatına göre hesaplanır."),
            "giris": (f"{ad} mağazasında fiyatı gerçekten düşen ürünler. Şu anda {len(ls)} ürün listede" +
                      (f"; en büyük düşüş %{o}." if o > 0 else ".") +
                      f" {AD}, {ad} indirimlerinin oranını ürünün son 10 gündeki en düşük fiyatına göre hesaplar; fiyat ve stok mağaza sayfasında kontrol edilir."),
            "urunler": ls, "ust": [("İndirimler", "/indirimler/")],
        })

    # özel sayfalar
    kac = sirala([u for u in urunler if u.get("kac")])
    cok = sorted([u for u in urunler if u.get("cok")], key=lambda u: ((u["cok"].get("s") or 999), -oran(u)))
    ozel = [
        {"yol": "/kacirilmaz-firsatlar/", "kisa": "Kaçırılmaz fırsatlar", "h1": "Kaçırılmaz Fırsatlar: Fiyatı Gerçekten Düşenler",
         "title": f"Kaçırılmaz Fırsatlar – Fiyatı Gerçekten Düşenler | {AD}",
         "aciklama": f"Son 10 günün en düşük fiyatından en az %10 ucuza inen {len(kac)} ürün. Trendyol, Hepsiburada, Amazon ve n11'in gerçek indirimleri, en büyük düşüş önce.",
         "giris": "Fiyatı, son 10 günde kaydettiğimiz en düşük fiyatından en az %10 aşağı inen ürünler. Mağazanın üstü çizili fiyatı kullanılmaz. Liste en büyük indirimden küçüğe sıralanır.",
         "urunler": kac},
        {"yol": "/cok-satanlar/", "kisa": "Çok satanlar", "h1": "En Çok Satanlar ve Güncel Fiyatları",
         "title": f"En Çok Satan Ürünler ve Fiyatları, {ay} | {AD}",
         "aciklama": f"Trendyol, Hepsiburada, Amazon ve n11'in kategori bazlı en çok satan {len(cok)} ürünü ve güncel fiyatları; fiyat geçmişiyle birlikte.",
         "giris": "Büyük mağazaların kategori bazlı en çok satan ürünleri. Fiyatlar mağaza sayfasından okunur ve ürünün fiyat geçmişiyle karşılaştırılır.",
         "urunler": cok},
    ]
    tum = sirala([u for u in urunler])
    en, o = ozet(tum)
    merkez = {"yol": "/indirimler/", "kisa": "Tüm indirimler", "h1": "Güncel İndirimler ve Fiyatı Düşen Ürünler",
              "title": f"Güncel İndirimler, {ay} – Fiyatı Düşen Ürünler | {AD}",
              "aciklama": f"Bugün fiyatı düşen {len(tum)} ürün; kategori ve mağazaya göre gerçek indirimler. İndirim oranı son 10 günün en düşük fiyatına göre hesaplanır.",
              "giris": (f"Trendyol, Hepsiburada, Amazon, n11 ve diğer mağazalarda fiyatı düşen {len(tum)} ürün" +
                        (f"; en büyük düşüş şu anda %{o}." if o > 0 else ".") +
                        " Aşağıdan kategori ya da mağaza seçerek o bölümün gerçek indirimlerini görebilirsiniz."),
              "urunler": tum}

    linkler_kat = [{"yol": s["yol"], "kisa": s["kisa"]} for s in kat_sayfa] + \
                  [{"yol": s["yol"], "kisa": s["kisa"]} for s in ozel]
    linkler_mag = [{"yol": s["yol"], "kisa": s["kisa"]} for s in mag_sayfa] + [{"yol": "/indirimler/", "kisa": "Tüm indirimler"}]

    sayfalar = [merkez] + ozel + kat_sayfa + mag_sayfa
    yollar = set()
    for s in sayfalar:
        if s["yol"] in yollar:      # kategori ve mağaza aynı adı taşırsa ikincisi atlanır
            continue
        yollar.add(s["yol"])
        yaz(s["yol"], sayfa_html(s, linkler_kat, linkler_mag, guncelleme, v))

    # artık kullanılmayan eski sayfaları kaldır (ör. bir kategori boşaldıysa)
    kok_ind = os.path.join(KOK, "indirimler")
    if os.path.isdir(kok_ind):
        for ad in os.listdir(kok_ind):
            p = os.path.join(kok_ind, ad)
            if os.path.isdir(p) and f"/indirimler/{ad}/" not in yollar:
                for f in os.listdir(p):
                    os.remove(os.path.join(p, f))
                os.rmdir(p)

    # sitemap.xml
    lm = iso(guncelleme)
    girdiler = [(SITE + "/", lm, "1.0")] + [(SITE + y, lm, "0.8") for y in sorted(yollar)] + [(SITE + "/yasal.html", None, "0.2")]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, mod, pr in girdiler:
        sm.append(f"<url><loc>{e(loc)}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + f"<priority>{pr}</priority></url>")
    sm.append("</urlset>")
    sm.append(f"<!-- uretici:{URETICI} -->")
    yaz("sitemap.xml", "\n".join(sm) + "\n")

    yaz("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")

    ana_sayfa_isle(linkler_kat, linkler_mag)
    yasal_isle()
    print(f"SEO · {len(yollar)} sayfa · {len(urunler)} ürün · güncelleme {tarih_yazi(guncelleme)}")


if __name__ == "__main__":
    main()
