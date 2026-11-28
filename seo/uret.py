#!/usr/bin/env python3
"""Düşero SEO üreticisi.

veri.json'dan Google'ın JavaScript çalıştırmadan okuyabileceği statik sayfalar üretir:
  /indirimler/                      tüm kategori ve mağazaların merkezi (sayfalı: /indirimler/2/ …)
  /indirimler/<kategori-veya-magaza>/   (sayfalı: …/2/, …/3/ … en fazla SAYFA_EN_FAZLA sayfa)
  /kacirilmaz-firsatlar/  /cok-satanlar/
  /kuponlar/  /kuponlar/<magaza>/   yalnızca verideki gerçek kupon kodlarından
  /hakkinda/                        Düşero nedir, nasıl çalışır?
  sitemap.xml  robots.txt  <indexnow-anahtarı>.txt
Ayrıca index.html ve yasal.html'e canonical, Open Graph ve yapılandırılmış veri ekler
(işaretli bloklar her çalışmada yeniden yazılır; site tasarımı güncellense de kaybolmaz).

Ürün kartları programın sunucuda yazdığı ürün sayfalarına (/u/<ad>-<kimlik>) bağlanır; adres programdaki
yayin.urun_sayfa_yolu ile birebir aynı kuralla hesaplanır (kasim-firsatlari/tests/test_seo.py iki tarafı karşılaştırır).
İndirim ölçüsü ve sıralama sitedeki app.js ile aynıdır (dusus / olcum / kacMi / siralayici).

Yalnızca Python standart kütüphanesi kullanır. Kullanım: python3 seo/uret.py [site_dizini] [--gerekirse]
GitHub Actions'ta saatte bir çalışır; site_dizini verilirse (önizleme) o klasöre yazar.
"""
import hashlib
import html
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

SITE = "https://dusero.com"
AD = "Düşero"
SLOGAN = "Acele etme, düşer o"
TELEGRAM = "https://t.me/dusero_tr"
KAPAK = f"{SITE}/paylasim.jpg"
TR = timezone(timedelta(hours=3))
_ARG = [a for a in sys.argv[1:] if not a.startswith("--")]
KOK = os.path.abspath(_ARG[0] if _ARG else os.path.join(os.path.dirname(__file__), ".."))
SEO_DIZIN = os.path.dirname(os.path.abspath(__file__))
SAYFA_URUN = 60          # bir sayfada gösterilecek ürün sayısı
SAYFA_EN_FAZLA = 10      # bir liste en fazla bu kadar sayfaya bölünür (10 × 60 = 600 ürün)
MAGAZA_ESIK = 10         # bu sayıdan az ürünü olan mağazaya ayrı sayfa açılmaz (yayin.py de bu eşiği kullanır)
ONE_CIKAN = 40           # ana sayfadaki "Bugünün öne çıkan indirimleri" listesindeki ürün sayısı
INDEXNOW_EN_FAZLA = 500  # (iş akışında) bir yayında IndexNow'a bildirilecek en fazla adres
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
         "Eylül", "Ekim", "Kasım", "Aralık"]
# Bu klasörlerin altındaki sayfaları yalnızca bu betik üretir; artık üretilmeyen sayfalar silinir
YONETILEN = ("indirimler", "kacirilmaz-firsatlar", "cok-satanlar", "kuponlar", "hakkinda")

# Kategoriye özgü kısa tanıtımlar (Google'ın sayfayı ayırt etmesi için her sayfada farklı metin)
KAT_METIN = {
    "elektronik": "Akıllı telefon, televizyon, kulaklık, akıllı saat ve diğer elektronik ürünlerde fiyatı gerçekten düşenler.",
    "bilgisayar": "Dizüstü bilgisayar, monitör, ekran kartı, SSD, oyun konsolu ve aksesuarlarda gerçek fiyat düşüşleri.",
    "beyaz": "Buzdolabı, çamaşır ve bulaşık makinesi, süpürge, airfryer ve küçük ev aletlerinde gerçek indirimler.",
    "kozmetik": "Parfüm, cilt bakımı, makyaj, saç bakımı ve tıraş ürünlerinde fiyatı gerçekten düşenler.",
    "giyim": "Mont, sweatshirt, pantolon, elbise ve diğer giyim ürünlerinde fiyatı gerçekten düşenler.",
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

# Sitedeki (app.js / yayin.py) gerçek kural; sayfalardaki tüm açıklamalar bu metinlerden gelir
KURAL_KISA = ("İndirim oranı mağazanın üstü çizili fiyatından değil, ürünün son 90 gün içinde kaydettiğimiz "
              "fiyatlarının ortancasından (olağan fiyatından) hesaplanır.")
KURAL_UZUN = (
    "Her ürünün fiyatı ve stoğu mağaza sayfasından (bazı çok satanlarda mağazanın çok satanlar listesinden) okunur. "
    + KURAL_KISA +
    " En az 3 fiyat kaydı olmayan üründe oran gösterilmez. Dönemin en düşük fiyatına inen ürünler (en az 7 günlük "
    "geçmişle) “Gerçek indirim”, olağan fiyatının en az %5 altındakiler “İyi fiyat”, en az 7 günlük geçmişe göre "
    "%10 ve üzeri düşenler “Kaçırılmaz” olarak işaretlenir. Önce fiyatı artırılıp sonra “indirim” diye sunulan "
    "ürünler bu etiketleri almaz. Fiyatlar mağazalarca anlık değişebilir; satın almadan önce mağazadaki son fiyatı "
    "kontrol edin.")
ORTAKLIK = (f"{AD} bağımsız bir fiyat takip sitesidir; satış yapmaz. Sitedeki bazı bağlantılar satış ortaklığı (reklam) "
            f"bağlantısıdır; bu bağlantılardan alışveriş yaptığınızda {AD} komisyon kazanabilir, ödediğiniz fiyat değişmez.")


# ---------- ayarlar ----------
AYAR_VARSAYILAN = {"google_dogrulama": "", "bing_dogrulama": "", "yandex_dogrulama": "",
                   "indexnow_anahtar": "", "urun_sayfasi_linki": True, "sayfa_en_fazla": 10}


def ayar_oku():
    a = dict(AYAR_VARSAYILAN)
    try:
        with open(os.path.join(SEO_DIZIN, "ayar.json"), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            a.update({k: v for k, v in d.items() if k in AYAR_VARSAYILAN})
    except (OSError, ValueError):
        pass
    return a


AYAR = ayar_oku()


# ---------- yardımcılar ----------
def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def kucuk(s):
    return (s or "").replace("I", "ı").replace("İ", "i").lower()


def slug(s):
    """Kategori/mağaza sayfası adresi. yayin.py'deki seo_slug ile birebir aynı olmalı (ürün sayfasındaki sayfa yolu)."""
    s = kucuk(s)
    for a, b in (("ç", "c"), ("ğ", "g"), ("ı", "i"), ("ö", "o"), ("ş", "s"), ("ü", "u"), ("â", "a"), ("î", "i"), ("û", "u")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "diger"


# Ürün sayfası adresi: yayin.py'deki _TR_HARF / urun_kisa_ad / urun_sayfa_yolu ile birebir aynı
_TR_HARF = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u",
                          "Ç": "c", "Ğ": "g", "I": "i", "İ": "i", "Ö": "o", "Ş": "s", "Ü": "u"})


def urun_kisa_ad(baslik):
    s = (baslik or "").translate(_TR_HARF).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > 70:
        s = s[:71].rsplit("-", 1)[0]
    return s or "urun"


def urun_yolu(u):
    """Ürünün sitedeki sayfası (/u/<ad>-<kimlik>); ayarda kapatılmışsa ana sayfadaki ayrıntı penceresi."""
    if not AYAR.get("urun_sayfasi_linki", True) or not u.get("id"):
        return f"/#u-{u.get('id') or ''}"
    return f"/u/{urun_kisa_ad(u.get('baslik'))}-{u['id']}"


def buyuk_bas(k):
    if not k:
        return k
    ilk = {"i": "İ", "ı": "I"}.get(k[0], k[0].upper())
    return ilk + k[1:]


def baslik_hali(s):
    return " ".join(w if (w.isupper() or w == "&" or not w[0].isalpha()) else buyuk_bas(w) for w in (s or "").split())


def de_eki(ad):
    """Mağaza adına bulunma eki (yayin._de ile aynı): Trendyol'da, n11'de, Amazon'da."""
    ad = (ad or "").strip()
    son = ad[-1:].lower()
    if son.isdigit():
        kalin, sert = son in "069", son in "345"
    else:
        unluler = [c for c in ad.lower().replace("I", "ı") if c in "aıoueiöü"]
        kalin, sert = bool(unluler) and unluler[-1] in "aıou", son in "fstkçşhp"
    return f"{ad}'{'t' if sert else 'd'}{'a' if kalin else 'e'}"


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


def gun_yazi(ts):
    d = datetime.fromtimestamp(ts, TR)
    return f"{d.day} {AYLAR[d.month - 1]}"


def iso(ts):
    return datetime.fromtimestamp(ts, TR).isoformat(timespec="seconds")


def kisalt(metin, n):
    """Kelime ortasında kesmeden en fazla n karakter."""
    metin = " ".join(str(metin or "").split())
    if len(metin) <= n:
        return metin
    k = metin[:n + 1].rsplit(" ", 1)[0].rstrip(" ,;:-–·")
    return k or metin[:n]


def ld_json(veri):
    """<script type=application/ld+json> içine güvenle konacak JSON (</script> kaçışı)."""
    return json.dumps(veri, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def aciklama_sec(bas, adet, dusen, en_oran, en_fazla=150):
    """Liste sayfası açıklaması: verideki sayılardan, en fazla en_fazla karakter (cümle ortasında kesmeden)."""
    sayi = f"{adet} ürün takipte" + (f", {dusen} üründe gerçek fiyat düşüşü" if dusen else "")
    eb = f", en büyük düşüş %{en_oran}" if en_oran > 0 else ""
    return ilk_uygun([f"{bas}: {sayi}{eb}. İndirim, ürünün fiyat geçmişine göre ölçülür.",
                      f"{bas}: {sayi}{eb}. İndirim fiyat geçmişine göre.",
                      f"{bas}: {sayi}{eb}.", f"{bas}: {adet} ürün takipte."], en_fazla)


def ilk_uygun(adaylar, en_fazla):
    for a in adaylar:
        if len(a) <= en_fazla:
            return a
    return adaylar[-1]


# ---------- indirim ölçüsü (site/app.js ile aynı) ----------
GUN = 86400
DUSUS_EN_AZ = 10       # app.js DUSUS_EN_AZ: "Kaçırılmaz" için en az %10 Düşero ölçümü
KARAR_SIRA = {"dip": 0, "iyi": 1, "sisirilmis": 3}


def olcum(u):
    """app.js olcum(): Düşero'nun kendi ölçtüğü indirim (yayin.gercek_indirim kararı)."""
    g = u.get("gercek") if isinstance(u.get("gercek"), dict) else {}
    if u.get("karar") == "sisirilmis" or g.get("d") != "gercek" or g.get("k") not in ("gecmis", "piyasa"):
        return None
    try:
        o, r = int(round(float(g.get("o") or 0))), float(g.get("r") or 0)
    except (TypeError, ValueError):
        return None
    if o <= 0 or not r > u["fiyat"]:
        return None
    return {"oran": o, "tl": r - u["fiyat"], "ref": r}


def dusus(u):
    """app.js dusus(): kartta gösterilen düşüş (geçmişe göre normal fiyat ya da Düşero ölçümü)."""
    if u.get("karar") == "sisirilmis":
        return None
    gy, nr = u.get("gercek_yuzde") or 0, u.get("normal") or 0
    if u.get("karar") in ("dip", "iyi") and gy > 0 and nr > u["fiyat"]:
        return {"oran": int(gy), "tl": nr - u["fiyat"], "ref": nr}
    return olcum(u)


def normallestir(u, an):
    """Ürüne bir kez hesaplanan ölçüleri ekler (_g: düşüş, _kac: Kaçırılmaz mı)."""
    g = dusus(u)
    u["_g"] = g
    o = olcum(u)
    u["_kac"] = bool(o and o["oran"] >= DUSUS_EN_AZ and (u.get("kac") or an - (u.get("ilk") or 0) <= GUN))


def indirim(u):
    return u.get("_g")


def oran(u):
    """app.js indirimOrani()."""
    i = indirim(u)
    return i["oran"] if i else max(0, int(u.get("gercek_yuzde") or 0))


def sirala(ls):
    """app.js siralayici() "Önerilen" sırası: Kaçırılmazlar, ölçülen düşüşü olanlar, karar, gerçek oran, yeni olan."""
    def anahtar(u):
        gy = u.get("gercek_yuzde")
        return (-int(bool(u.get("_kac"))), -int(bool(oran(u))), KARAR_SIRA.get(u.get("karar"), 2),
                -(gy if gy is not None else -1000), -(u.get("yuzde") or 0), -(u.get("ilk") or 0))
    return sorted(ls, key=anahtar)


def kac_sirala(ls):
    """app.js kacSiralayici(): oran, TL farkı, yeni olan."""
    def anahtar(u):
        o = olcum(u)
        return (-(o["oran"] if o else 0), -(o["tl"] if o else 0), -(u.get("ilk") or 0))
    return sorted(ls, key=anahtar)


ETIKET = {
    "dip": ("Gerçek indirim", "k-dip"),
    "iyi": ("İyi fiyat", "k-iyi"),
}


# ---------- sayfa parçaları ----------
def kart(u):
    i = indirim(u)
    resim = u.get("resim")
    gorsel = (f'<img src="{e(resim)}" alt="{e(u["baslik"])}" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
              if resim else "")
    rozet = f'<span class="oran-rozet">%{i["oran"]}</span>' if i and i["oran"] > 0 else ""
    eski = f'<s class="eski">{tl(i["ref"])}</s>' if i else ""
    etk = ""
    if u.get("_kac"):
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
        f'<a class="kart-link" href="{e(urun_yolu(u))}">'
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
.seo-sayfalar{justify-content:center;margin:20px 0 6px}
.seo-blok{margin:26px 0 8px}.seo-blok h2{font-size:18px;margin:0 0 6px}.seo-blok h3{font-size:15.5px;margin:16px 0 4px}.seo-blok p{color:var(--gri-yazi);line-height:1.55;max-width:760px}
.seo-blok ul.seo-madde{color:var(--gri-yazi);line-height:1.55;max-width:760px;padding-left:20px}
.seo-tumu{margin:18px 0 6px;text-align:center}
.seo-kpn{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin:6px 0 10px}
.seo-kpn .kpn-kod{user-select:all}.seo-kpn .kpn-not{margin:8px 0 0}
.kart .kosul,.kart .cok,.kart .etk{display:inline-block}
@media (max-width:719px){body.seo-sayfa{padding-bottom:0}}
</style>"""


def link_listesi(sayfalar, aktif=None):
    li = []
    for s in sayfalar:
        cur = ' aria-current="page"' if s["yol"] == aktif else ""
        li.append(f'<li><a href="{s["yol"]}"{cur}>{e(s["kisa"])}</a></li>')
    return '<ul class="seo-linkler">' + "".join(li) + "</ul>"


def sayfa_yolu(yol, n):
    return yol if n <= 1 else f"{yol}{n}/"


def sayfa_gezinti(yol, n, toplam):
    """Sayfa numaraları (‹ Önceki · 1 2 3 · Sonraki ›); tek sayfada boş."""
    if toplam <= 1:
        return ""
    li = []
    if n > 1:
        li.append(f'<li><a href="{sayfa_yolu(yol, n - 1)}" rel="prev">‹ Önceki sayfa</a></li>')
    for k in range(1, toplam + 1):
        cur = ' aria-current="page"' if k == n else ""
        li.append(f'<li><a href="{sayfa_yolu(yol, k)}"{cur}>{k}</a></li>')
    if n < toplam:
        li.append(f'<li><a href="{sayfa_yolu(yol, n + 1)}" rel="next">Sonraki sayfa ›</a></li>')
    return '<nav aria-label="Sayfalar"><ul class="seo-linkler seo-sayfalar">' + "".join(li) + "</ul></nav>"


def sayfa_en_fazla():
    """Bir listenin en fazla sayfa sayısı (seo/ayar.json "sayfa_en_fazla"; 1–20, varsayılan SAYFA_EN_FAZLA)."""
    try:
        return max(1, min(20, int(AYAR.get("sayfa_en_fazla") or SAYFA_EN_FAZLA)))
    except (TypeError, ValueError):
        return SAYFA_EN_FAZLA


def sayfa_sayisi(s):
    if s.get("tek"):
        return 1
    return max(1, min(sayfa_en_fazla(), math.ceil(len(s.get("urunler") or []) / SAYFA_URUN)))


def cerceve(baslik, aciklama, url, govde, ld, v, tv, ek_head=""):
    """Tüm statik sayfaların ortak kabuğu (üst bant, alt bilgi, stil)."""
    tema = f'<link rel="stylesheet" href="/tema.css?v={e(tv)}">\n' if tv else ""
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(baslik)}</title>
<meta name="description" content="{e(aciklama)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#14213d">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{AD}">
<meta property="og:locale" content="tr_TR">
<meta property="og:title" content="{e(baslik)}">
<meta property="og:description" content="{e(aciklama)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{KAPAK}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
{ek_head}<link rel="icon" href="/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/ikon-192.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="stylesheet" href="/stil.css?v={e(v)}">
{tema}{EK_STIL}
<script type="application/ld+json">{ld_json(ld)}</script>
</head>
<body class="seo-sayfa">
<header class="ust">
<div class="kap ust-ic">
<a class="marka" href="/" aria-label="{AD} ana sayfa"><img class="logo-resim" src="/logo-koyu.png?v={e(v)}" width="400" height="149" alt="{AD}"></a>
<a class="dugme ikincil" href="/">Tüm fırsatlar</a>
</div>
</header>
<main class="kap">
{govde}
</main>
<footer class="alt">
<div class="kap alt-ic">
<div><span class="marka-ad">{AD}</span>
<p>{e(ORTAKLIK)}</p></div>
<nav aria-label="Yasal" class="alt-menu"><a href="/hakkinda/">{AD} nedir?</a> <a href="/yasal.html">Yasal bilgiler</a> <a href="/yasal.html#kvkk">Kişisel veriler</a> <a href="/yasal.html#iletisim">İletişim</a></nav>
</div>
<p class="kap telif">© {datetime.now(TR).year} {AD}</p>
</footer>
</body>
</html>
"""


def kirinti_html(kirinti, yol):
    return " › ".join(f'<a href="{y}">{e(ad)}</a>' if y != yol else e(ad) for ad, y in kirinti)


def kirinti_ld(kirinti):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": ad, "item": SITE + y}
                                for i, (ad, y) in enumerate(kirinti)]}


def alt_bloklar(tum_kat, tum_mag, aktif):
    return f"""<section class="seo-blok">
<h2>Kategoriye göre indirimler</h2>
{link_listesi(tum_kat, aktif)}
<h2>Mağazaya göre indirimler</h2>
{link_listesi(tum_mag, aktif)}
</section>
<section class="seo-blok">
<h2>{AD} indirimleri nasıl kontrol ediyor?</h2>
<p>{e(KURAL_UZUN)}</p>
<p>Fiyat düştüğü anda haber almak için <a href="{TELEGRAM}" rel="noopener">{AD} Telegram kanalına</a> katılabilirsiniz. <a href="/hakkinda/">{AD} nedir, nasıl çalışır?</a></p>
</section>"""


def sayfa_html(s, n, tum_kat, tum_mag, guncelleme, v, tv):
    """Bir liste sayfasının n. sayfası."""
    toplam = sayfa_sayisi(s)
    yol = sayfa_yolu(s["yol"], n)
    url = SITE + yol
    ek = f" – Sayfa {n}" if n > 1 else ""
    baslik = s["title"](ek) if callable(s["title"]) else s["title"] + ek
    aciklama = s["aciklama"] if n == 1 else ilk_uygun([f"Sayfa {n}/{toplam} · " + s["aciklama"],
                                                        f"Sayfa {n} · " + s["aciklama"], s["aciklama"]], 165)
    kirinti = [("Ana sayfa", "/")] + s.get("ust", []) + [(s["kisa"], s["yol"])]
    if n > 1:
        kirinti.append((f"Sayfa {n}", yol))
    bas = (n - 1) * SAYFA_URUN
    gosterilen = s["urunler"][bas:bas + SAYFA_URUN]
    ld = [
        kirinti_ld(kirinti),
        {"@context": "https://schema.org", "@type": "CollectionPage",
         "name": s["h1"] + ek, "description": aciklama, "url": url, "inLanguage": "tr-TR",
         "dateModified": iso(guncelleme),
         "isPartOf": {"@type": "WebSite", "name": AD, "url": SITE + "/"}},
    ]
    if gosterilen:
        ld.append({"@context": "https://schema.org", "@type": "ItemList", "name": s["h1"] + ek,
                   "numberOfItems": len(gosterilen),
                   "itemListElement": [{"@type": "ListItem", "position": bas + i + 1,
                                        "url": SITE + urun_yolu(u) if urun_yolu(u).startswith("/u/") else SITE + "/",
                                        "name": u["baslik"]}
                                       for i, u in enumerate(gosterilen)]})
    ek_head = ""
    if n > 1:
        ek_head += f'<link rel="prev" href="{SITE + sayfa_yolu(s["yol"], n - 1)}">\n'
    if n < toplam:
        ek_head += f'<link rel="next" href="{SITE + sayfa_yolu(s["yol"], n + 1)}">\n'
    kartlar = "".join(kart(u) for u in gosterilen)
    bos = '<p class="durum">Şu anda bu bölümde yayında ürün yok; liste gün içinde güncellenir.</p>' if not s["urunler"] else ""
    adet = len(s["urunler"])
    zaman = f"Son güncelleme: {tarih_yazi(guncelleme)} · {adet} ürün"
    if toplam > 1:
        zaman += f" · sayfa {n}/{toplam}"
        if adet > toplam * SAYFA_URUN:
            zaman += f" (ilk {toplam * SAYFA_URUN} ürün listelenir)"
    giris = s["giris"] if n == 1 else f"{s['h1']} listesinin {n}. sayfası. " + s["giris"]
    govde = f"""<nav class="seo-yol" aria-label="Sayfa yolu">{kirinti_html(kirinti, yol)}</nav>
<h1>{e(s["h1"] + ek)}</h1>
<p class="seo-giris">{e(giris)}</p>
<p class="seo-zaman">{zaman}</p>
{bos}<div class="izgara">{kartlar}</div>
{sayfa_gezinti(s["yol"], n, toplam)}
<p class="seo-tumu"><a class="dugme turuncu" href="/">Tüm fırsatları ve fiyat geçmişlerini gör</a></p>
{alt_bloklar(tum_kat, tum_mag, s["yol"])}"""
    return cerceve(baslik, aciklama, url, govde, ld, v, tv, ek_head)


# ---------- kuponlar ----------
MAGAZA_RENK = {"trendyol": "#f27a1a", "hepsiburada": "#ff6000", "amazon": "#232f3e", "n11": "#7d2ae8", "pazarama": "#0f6bff",
               "ciceksepeti": "#5a9a2f", "teknosa": "#0b4ea2", "mediamarkt": "#df0000", "vatan": "#d6001c", "boyner": "#111111",
               "karaca": "#9b1b30", "migros": "#ff7f00", "a101": "#00a0e3", "getir": "#5d3ebc", "lcwaikiki": "#1e3c96",
               "koton": "#000000", "defacto": "#1f2a44"}


def magaza_rengi(k):
    """app.js magazaRengi()."""
    if k in MAGAZA_RENK:
        return MAGAZA_RENK[k]
    h = 0
    for c in str(k):
        h = (h * 31 + ord(c)) % 360
    return f"hsl({h} 55% 42%)"


def kuponlari_ayikla(veri, an):
    """veri.json'daki kuponlar: yalnızca kodu ve mağazası olan, son günü geçmemiş kayıtlar (hiçbir şey uydurulmaz)."""
    sonuc, gorulen = [], set()
    for k in veri.get("kuponlar") or []:
        if not isinstance(k, dict) or not k.get("kod") or not (k.get("magaza_ad") or k.get("magaza")):
            continue
        if k.get("son") and k["son"] < an:
            continue
        anahtar = (k.get("magaza"), k["kod"])
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        sonuc.append(k)
    return sonuc


def kupon_metni(k):
    """app.js kuponMetni()."""
    if k.get("tutar") and k.get("limit"):
        return tl(k["tutar"]), f"{tl(k['limit'])} ve üzeri alışverişe"
    if k.get("tutar"):
        return tl(k["tutar"]), "indirim"
    return "Kod", "indirim kodu"


def kupon_karti(k):
    ad = k.get("magaza_ad") or k.get("magaza")
    buyuk, alt = kupon_metni(k)
    etk = [x for x in (k.get("ilk") and "İlk siparişe özel", k.get("uygulama") and "Uygulamada geçerli",
                       k.get("son") and f"Son gün: {gun_yazi(k['son'])}") if x]
    t = k.get("teyit") if isinstance(k.get("teyit"), dict) else {}
    kontrol = []
    if t.get("s") == "kod" and t.get("z"):
        kontrol.append(f"Kod kampanya sayfasında görüldü ({tarih_yazi(t['z'])})")
    elif t.get("s") == "acik" and t.get("z"):
        kontrol.append(f"Kampanya sayfası açık ({tarih_yazi(t['z'])})")
    if t.get("iyi"):
        kontrol.append(f"{int(t['iyi'])} ziyaretçi “çalıştı” dedi")
    git = (f'<a class="kpn-git" href="{e(k["link"])}" target="_blank" rel="nofollow sponsored noopener">'
           f'{e(ad)} kampanya sayfası ›</a>' if isinstance(k.get("link"), str) and k["link"].startswith("http") else "")
    return (f'<li class="kpn" style="--m:{e(magaza_rengi(k.get("magaza") or ad))}">'
            f'<div class="kpn-bas"><div class="kpn-kim"><span class="kpn-magaza">{e(ad)}</span>'
            f'<span class="kpn-zaman">paylaşıldı {e(tarih_yazi(k["ts"])) if k.get("ts") else ""}</span></div>'
            f'<div class="kpn-tutar"><b>{e(buyuk)}</b><span>{e(alt)}</span></div></div>'
            '<div class="kpn-govde">'
            + (('<div class="kpn-etkler">' + "".join(f'<span class="kpn-etk">{e(x)}</span>' for x in etk) + "</div>") if etk else "")
            + f'<div class="kpn-alt"><span class="kpn-kod">{e(k["kod"])}</span></div>'
            + git
            + (f'<p class="kpn-not">{e(" · ".join(kontrol))}</p>' if kontrol else "")
            + "</div></li>")


KUPON_KURAL = ("Kodlar fırsat kanallarında ve forumlarda paylaşılan mağaza kodlarıdır. Kodun paylaşıldığı kampanya sayfası "
               "kontrol edilir; sayfa kaldırılmışsa ya da “kampanya sona erdi” yazıyorsa, kanal kodun bittiğini "
               "söylediyse veya ziyaretçiler “çalışmadı” diye bildirdiyse kod listeden çıkar. Bitiş tarihi yazılmayan "
               "kod en fazla 6 saat (forumda hâlâ etkin görünen kod en fazla 48 saat), tarihi yazılan kod son gününe "
               "kadar gösterilir. Kodun sepette uygulanıp uygulanmadığını biz denemiyoruz; mağaza kodu kaldırmış ya da "
               "kullanım limiti dolmuş olabilir.")


def kupon_sayfasi_html(s, kuponlar, tum_kat, tum_mag, magaza_sayfalari, guncelleme, v, tv):
    url = SITE + s["yol"]
    kirinti = [("Ana sayfa", "/")] + s.get("ust", []) + [(s["kisa"], s["yol"])]
    if kuponlar:
        liste = '<ul class="kpn-liste seo-kpn">' + "".join(kupon_karti(k) for k in kuponlar) + "</ul>"
    else:
        hedef = s.get("magaza_sayfa")
        liste = ('<p class="kpn-bos">Şu an doğrulanmış kupon kodu yok. Mağazalar yeni bir kod paylaştığında burada '
                 'görünür.' + (f' Bu arada <a href="{hedef}">{e(s.get("magaza_ad"))} indirimlerine</a> bakabilirsiniz.'
                               if hedef else " Bu arada mağazalardaki gerçek fiyat düşüşlerine bakabilirsiniz.") + "</p>")
    mag_link = ""
    if magaza_sayfalari:
        mag_link = (f'<h2>Kupon kodu olan mağazalar</h2>{link_listesi(magaza_sayfalari, s["yol"])}')
    ld = [kirinti_ld(kirinti),
          {"@context": "https://schema.org", "@type": "CollectionPage", "name": s["h1"], "description": s["aciklama"],
           "url": url, "inLanguage": "tr-TR", "dateModified": iso(guncelleme),
           "isPartOf": {"@type": "WebSite", "name": AD, "url": SITE + "/"}}]
    govde = f"""<nav class="seo-yol" aria-label="Sayfa yolu">{kirinti_html(kirinti, s["yol"])}</nav>
<h1>{e(s["h1"])}</h1>
<p class="seo-giris">{e(s["giris"])}</p>
<p class="seo-zaman">Son güncelleme: {tarih_yazi(guncelleme)} · {len(kuponlar)} kod · liste saatte bir yenilenir; en güncel hâli ana sayfadaki “Güncel kuponlar” kutusundadır.</p>
{liste}
<section class="seo-blok">
{mag_link}
<h2>Kupon kodları nasıl kontrol ediliyor?</h2>
<p>{e(KUPON_KURAL)}</p>
</section>
<p class="seo-tumu"><a class="dugme turuncu" href="/">Tüm fırsatları ve fiyat geçmişlerini gör</a></p>
{alt_bloklar(tum_kat, tum_mag, s["yol"])}"""
    return cerceve(s["title"], s["aciklama"], url, govde, ld, v, tv)


# ---------- hakkında ----------
def hakkinda_sss(magaza_adlari):
    """Görünen ve JSON-LD'ye giden soru-cevaplar (ikisi de buradan; birebir aynı)."""
    return [
        (f"{AD} nedir?",
         f"{AD} (Dusero), online mağazalarda fiyatı gerçekten düşen ürünleri gösteren bağımsız bir fiyat takip "
         f"sitesidir. Adı “düşer o” sözünden gelir; sloganımız da budur: {SLOGAN}."),
        (f"{AD} indirimin gerçek olup olmadığını nasıl anlıyor?", KURAL_KISA +
         " Mağazanın gösterdiği üstü çizili fiyat oran hesabında kullanılmaz; önce fiyatı artırılıp sonra “indirim” "
         "diye sunulan ürünler “Gerçek indirim” ya da “İyi fiyat” etiketi almaz."),
        (f"{AD} hangi mağazaları takip ediyor?",
         ("Şu anda listede ürünü olan mağazalar: " + ", ".join(magaza_adlari) + ".") if magaza_adlari
         else "Takip edilen mağazaların listesi her yayında verilerden güncellenir."),
        (f"{AD} satış yapıyor mu?", ORTAKLIK),
        ("Kupon kodları nereden geliyor?", KUPON_KURAL),
        ("Fiyat düşünce nasıl haber alırım?",
         f"Gerçek indirimler düştüğü anda {AD} Telegram kanalında (t.me/dusero_tr) paylaşılır; uygulama indirmek gerekmez."),
    ]


def hakkinda_html(magazalar, mag_sayfa_yol, guncelleme, v, tv, tum_kat, tum_mag):
    yol = "/hakkinda/"
    url = SITE + yol
    adlar = [ad for ad, _ in magazalar]
    sss = hakkinda_sss(adlar)
    baslik = f"{AD} Nedir, Nasıl Çalışır? Dusero Fiyat Takip | {AD}"
    aciklama = (f"{AD} (Dusero) bağımsız bir fiyat takip sitesi: indirimi ürünün fiyat geçmişine göre ölçer, "
                "mağazaları karşılaştırır, kuponları listeler. Acele etme, düşer o.")
    kirinti = [("Ana sayfa", "/"), (f"{AD} nedir?", yol)]
    mag_li = "".join(
        f'<li><a href="{mag_sayfa_yol[ad]}">{e(ad)}</a></li>' if ad in mag_sayfa_yol else f"<li><span>{e(ad)}</span></li>"
        for ad, _ in magazalar)
    ld = [
        kirinti_ld(kirinti),
        {"@context": "https://schema.org", "@type": "AboutPage", "name": f"{AD} nedir, nasıl çalışır?", "url": url,
         "description": aciklama, "inLanguage": "tr-TR",
         "about": {"@id": SITE + "/#org"}, "isPartOf": {"@type": "WebSite", "name": AD, "url": SITE + "/"}},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": s, "acceptedAnswer": {"@type": "Answer", "text": c}} for s, c in sss]},
    ]
    govde = f"""<nav class="seo-yol" aria-label="Sayfa yolu">{kirinti_html(kirinti, yol)}</nav>
<h1>{AD} nedir, nasıl çalışır?</h1>
<p class="seo-giris">{AD} (bazen “Dusero” ya da “düşer o” diye de yazılıyor), Türkiye'deki online mağazalarda fiyatı gerçekten düşen ürünleri takip eden bağımsız bir fiyat takip sitesidir. Adı “düşer o” sözünden gelir; sloganımız da oradan: <b>{SLOGAN}.</b> Aradığınız ürünün fiyatı bugün yüksekse acele etmeyin; düştüğünde burada ve Telegram kanalımızda görürsünüz.</p>
<section class="seo-blok">
<h2>Nasıl çalışır?</h2>
<ul class="seo-madde">
<li><b>Takip:</b> Fırsat kanallarında, mağazaların çok satanlar listelerinde ve ürün akışlarında görülen ürünlerin fiyatı ve stoğu mağaza sayfasından okunur; her okuma fiyat geçmişine kaydedilir.</li>
<li><b>Ölçüm:</b> {e(KURAL_KISA)} En az 3 fiyat kaydı olmayan üründe oran gösterilmez.</li>
<li><b>Etiketler:</b> Dönemin en düşük fiyatına inen ürünler (en az 7 günlük geçmişle) “Gerçek indirim”, olağan fiyatının en az %5 altındakiler “İyi fiyat”, en az 7 günlük geçmişe göre %10 ve üzeri düşenler “Kaçırılmaz” olarak işaretlenir; fiyatı önce artırılıp “indirim” diye sunulan ürünler bu etiketleri almaz.</li>
<li><b>Karşılaştırma:</b> Aynı ürün başka mağazalarda da bulunduysa ürün sayfasında mağazalardaki fiyatlar yan yana gösterilir.</li>
<li><b>Kuponlar:</b> Paylaşılan mağaza kupon kodları kontrol edilerek <a href="/kuponlar/">kupon sayfasında</a> listelenir.</li>
</ul>
<h2>Takip edilen mağazalar</h2>
<p>Şu anda listede ürünü olan mağazalar ({len(magazalar)} mağaza; liste her yayında güncellenir):</p>
<ul class="seo-linkler">{mag_li}</ul>
<h2>Sık sorulan sorular</h2>
{"".join(f"<h3>{e(s)}</h3><p>{e(c)}</p>" for s, c in sss)}
<h2>İletişim</h2>
<p>Fiyat düştüğü anda haber almak için <a href="{TELEGRAM}" rel="noopener">{AD} Telegram kanalına</a> katılabilirsiniz. Soru, öneri ve düzeltme talepleri için <a href="/yasal.html#iletisim">iletişim bilgilerimiz</a>.</p>
</section>
<p class="seo-tumu"><a class="dugme turuncu" href="/">Tüm fırsatları ve fiyat geçmişlerini gör</a></p>
{alt_bloklar(tum_kat, tum_mag, yol)}"""
    return cerceve(baslik, aciklama, url, govde, ld, v, tv)


# ---------- index.html / yasal.html'e eklenecek bloklar ----------
BAS_ISARET, SON_ISARET = "<!--seo:bas-->", "<!--seo:son-->"
LBAS, LSON = "<!--seo-linkler:bas-->", "<!--seo-linkler:son-->"
ANA_TITLE = f"{AD} · Gerçek İndirim, Fırsat, Kupon ve Fiyat Karşılaştırma"
BUYUK_MAGAZALAR = ("Trendyol", "Hepsiburada", "Amazon", "n11")


def ana_aciklama(magaza_adlari):
    """Ana sayfa açıklaması: mağaza adları veriden (yalnızca listede olanlar)."""
    var = [m for m in BUYUK_MAGAZALAR if m in magaza_adlari] or list(magaza_adlari)[:4]
    if len(var) > 1:
        mag = ", ".join(var[:-1]) + " ve " + de_eki(var[-1])
    elif var:
        mag = de_eki(var[0])
    else:
        mag = "online mağazalarda"
    adaylar = [
        f"{AD}: {mag} fiyatı gerçekten düşen ürünler, indirim kuponları ve fiyat karşılaştırma. "
        "İndirim, ürünün kendi fiyat geçmişine göre ölçülür.",
        f"{AD}: {mag} fiyatı gerçekten düşen ürünler ve indirim kuponları. İndirim, fiyat geçmişine göre ölçülür.",
        f"{AD}: fiyatı gerçekten düşen ürünler, indirim kuponları ve fiyat karşılaştırma. İndirim fiyat geçmişine göre ölçülür.",
    ]
    return ilk_uygun(adaylar, 160)


def blok_degistir(metin, bas, son, yeni, once):
    """bas..son arası bloğu yeniler; yoksa `once` dizesinden hemen önce ekler."""
    desen = re.compile(re.escape(bas) + r".*?" + re.escape(son), re.S)
    parca = bas + yeni + son
    if desen.search(metin):
        return desen.sub(lambda _: parca, metin, count=1)
    i = metin.find(once)
    return metin if i < 0 else metin[:i] + parca + " " + metin[i:]


def ana_ld(arama_var):
    site = {"@context": "https://schema.org", "@type": "WebSite", "@id": SITE + "/#site", "name": AD,
            "alternateName": ["Dusero", "Düşer O", "Düşer o", "dusero.com", "Düşero Fırsat"], "url": SITE + "/",
            "inLanguage": "tr-TR", "publisher": {"@id": SITE + "/#org"}}
    if arama_var:
        site["potentialAction"] = {"@type": "SearchAction",
                                   "target": {"@type": "EntryPoint", "urlTemplate": SITE + "/?q={search_term_string}"},
                                   "query-input": "required name=search_term_string"}
    return [
        {"@context": "https://schema.org", "@type": "Organization", "@id": SITE + "/#org", "name": AD,
         "alternateName": ["Dusero", "Düşer O", "dusero.com"], "slogan": SLOGAN,
         "url": SITE + "/", "logo": SITE + "/ikon-512.png", "sameAs": [TELEGRAM]},
        site,
    ]


def dogrulama_etiketleri():
    """seo/ayar.json'da doldurulan arama motoru doğrulama kodları; boşsa hiçbir şey."""
    etk = []
    for alan, ad in (("google_dogrulama", "google-site-verification"), ("bing_dogrulama", "msvalidate.01"),
                     ("yandex_dogrulama", "yandex-verification")):
        deger = str(AYAR.get(alan) or "").strip()
        m = re.search(r'content="([^"]+)"', deger)       # yanlışlıkla bütün <meta> etiketi yapıştırıldıysa
        deger = m.group(1) if m else deger
        if deger and re.fullmatch(r"[\w\-.:=+/]{4,200}", deger):
            etk.append(f'<meta name="{ad}" content="{e(deger)}">')
    return " ".join(etk)


def arama_destekli():
    """app.js açılışta ?q= parametresini arama kutusuna alıyorsa SearchAction eklenebilir."""
    try:
        js = open(os.path.join(KOK, "app.js"), encoding="utf-8").read()
    except OSError:
        return False
    return "dusero-q-param" in js or bool(re.search(r"""URLSearchParams\(location\.search\)\.get\(["']q["']\)""", js))


ANA_STIL = ('<style>.seo-linkler{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 16px;padding:0;list-style:none}'
            '.seo-linkler a{display:inline-block;padding:7px 12px;border:1px solid var(--cizgi-koyu);border-radius:999px;'
            'background:var(--kart);color:var(--murekkep);text-decoration:none;font-size:14px;font-weight:600}'
            '.seo-blok h2{font-size:18px;margin:0 0 4px}'
            '.seo-blok p{color:var(--gri-yazi);line-height:1.55;max-width:760px;margin:6px 0 16px}'
            '.seo-urunler{list-style:none;margin:8px 0 18px;padding:0;display:grid;'
            'grid-template-columns:repeat(auto-fill,minmax(300px,1fr));column-gap:22px}'
            '.seo-urunler li{display:flex;align-items:baseline;gap:8px;min-width:0;padding:7px 0;'
            'border-bottom:1px solid var(--cizgi);font-size:14px}'
            '.seo-urunler a{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
            'color:var(--murekkep);text-decoration:none;font-weight:600}.seo-urunler a:hover{text-decoration:underline}'
            '.seo-urunler b{white-space:nowrap}.seo-urunler span{white-space:nowrap;color:var(--soluk);font-size:12.5px}'
            '.seo-urunler i{font-style:normal;font-weight:800;color:var(--vurgu-yazi);white-space:nowrap}</style>')


def one_cikanlar_html(one_cikan):
    li = []
    for u in one_cikan:
        i = indirim(u)
        li.append(f'<li><a href="{e(urun_yolu(u))}">{e(u["baslik"])}</a>'
                  + (f'<i>%{i["oran"]}</i>' if i and i["oran"] > 0 else "")
                  + f'<b>{tl(u["fiyat"])}</b><span>{e(u.get("magaza_ad"))}</span></li>')
    return '<ol class="seo-urunler">' + "".join(li) + "</ol>"


def ana_sayfa_isle(tum_kat, tum_mag, one_cikan, magaza_adlari, guncelleme):
    yol = os.path.join(KOK, "index.html")
    if not os.path.exists(yol):
        return
    m = open(yol, encoding="utf-8").read()
    ilk = m
    m = re.sub(r"<title>.*?</title>", lambda _: f"<title>{e(ANA_TITLE)}</title>", m, count=1, flags=re.S)
    aciklama = ana_aciklama(magaza_adlari)
    m = re.sub(r'<meta name="description" content="[^"]*">', lambda _: f'<meta name="description" content="{e(aciklama)}">',
               m, count=1)
    m = re.sub(r'<meta property="og:image" content="[^"]*">\s*', "", m)  # göreli og:image yerine mutlak olan eklenir
    dog = dogrulama_etiketleri()
    bas = (f'<link rel="canonical" href="{SITE}/"> <meta name="robots" content="index, follow, max-image-preview:large"> '
           + (dog + " " if dog else "") +
           f'<meta property="og:type" content="website"> <meta property="og:site_name" content="{AD}"> '
           f'<meta property="og:locale" content="tr_TR"> <meta property="og:url" content="{SITE}/"> '
           f'<meta property="og:image" content="{KAPAK}"> <meta property="og:image:width" content="1200"> '
           f'<meta property="og:image:height" content="630"> <meta name="twitter:card" content="summary_large_image"> '
           f'<script type="application/ld+json">{ld_json(ana_ld(arama_destekli()))}</script>')
    m = blok_degistir(m, BAS_ISARET, SON_ISARET, bas, "</head>")
    one = ""
    if one_cikan:
        one = ('<h2 id="seo-one-baslik">Bugünün öne çıkan indirimleri</h2>'
               f'<p>{gun_yazi(guncelleme)} {datetime.fromtimestamp(guncelleme, TR):%H:%M} itibarıyla {AD} listesinde '
               'öne çıkan ürünler; fiyat geçmişi ve mağaza karşılaştırması ürün sayfasında.</p>'
               + one_cikanlar_html(one_cikan))
    nedir = (f'<h2>{AD} nedir?</h2>'
             f'<p>{AD}, online mağazalarda fiyatı gerçekten düşen ürünleri takip eden bağımsız bir fiyat takip sitesidir; '
             f'sloganımız da adımızdan geliyor: “{SLOGAN}.” İndirimi mağazanın üstü çizili fiyatına göre değil, '
             'ürünün kendi fiyat geçmişine göre ölçer, aynı ürünü başka mağazalarda bulduğunda fiyatları yan yana '
             'gösterir ve paylaşılan <a href="/kuponlar/">indirim kuponlarını</a> kontrol ederek listeler. '
             f'<a href="/hakkinda/">{AD} nasıl çalışır?</a></p>')
    linkler = (f'<section class="bolum seo-blok" aria-labelledby="{"seo-one-baslik" if one else "seo-kat-baslik"}">'
               + ANA_STIL + one +
               '<h2 id="seo-kat-baslik">Kategoriye göre indirimler</h2>' + link_listesi(tum_kat) +
               '<h2>Mağazaya göre indirimler</h2>' + link_listesi(tum_mag) + nedir + "</section>")
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
def surum(desen=r"stil\.css\?v=([\w.\-]+)", varsayilan="1"):
    try:
        m = open(os.path.join(KOK, "index.html"), encoding="utf-8").read()
        r = re.search(desen, m)
        return r.group(1) if r else varsayilan
    except OSError:
        return varsayilan


def yaz(yol, icerik):
    tam = os.path.join(KOK, yol.strip("/"), "index.html") if yol.endswith("/") else os.path.join(KOK, yol.strip("/"))
    os.makedirs(os.path.dirname(tam), exist_ok=True)
    if os.path.exists(tam):
        with open(tam, encoding="utf-8") as f:
            if f.read() == icerik:
                return
    with open(tam, "w", encoding="utf-8") as f:
        f.write(icerik)


def eskileri_temizle(yazilan):
    """YONETILEN klasörlerde artık üretilmeyen sayfaları (index.html) siler, boşalan klasörleri kaldırır.
    Alt klasörler (sayfa numaraları: /indirimler/kitap/7/) de dahil."""
    silinen = 0
    for kok_ad in YONETILEN:
        kok = os.path.join(KOK, kok_ad)
        if not os.path.isdir(kok):
            continue
        for dizin, _, dosyalar in os.walk(kok, topdown=False):
            goreli = os.path.relpath(dizin, KOK).replace(os.sep, "/")
            url = "/" + goreli.strip("/") + "/"
            for f in dosyalar:
                if f == "index.html" and url in yazilan:
                    continue
                if f == "index.html" or f.endswith(".gz"):
                    os.remove(os.path.join(dizin, f))
                    silinen += 1
            try:
                if not os.listdir(dizin):
                    os.rmdir(dizin)
            except OSError:
                pass
    return silinen


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
        if not isinstance(u, dict) or u.get("id") in gor:
            continue
        gor.add(u.get("id"))
        tekil.append(u)
    return veri, tekil


def _uretici_ozeti():
    h = hashlib.sha1(open(os.path.abspath(__file__), "rb").read())
    try:
        h.update(open(os.path.join(SEO_DIZIN, "ayar.json"), "rb").read())
    except OSError:
        pass
    return h.hexdigest()[:12]


URETICI = _uretici_ozeti()


def gerek_yok():
    """Ana sayfada SEO bloğu duruyor ve sitemap son 55 dakikada yenilendiyse çalışmaya gerek yok."""
    try:
        ana = open(os.path.join(KOK, "index.html"), encoding="utf-8").read()
        sm = open(os.path.join(KOK, "sitemap.xml"), encoding="utf-8").read()
        if f"<!-- uretici:{URETICI} -->" not in sm:      # üretici kodu ya da ayarı değiştiyse her zaman yeniden üret
            return False
        r = re.search(r"<lastmod>([^<]+)</lastmod>", sm)
        son = datetime.fromisoformat(r.group(1)).timestamp() if r else 0
    except (OSError, ValueError):
        return False
    return BAS_ISARET in ana and LBAS in ana and time.time() - son < 55 * 60


def magaza_listesi_metni(adlar, en_fazla=4, ve_digerleri=False):
    """Veride bulunan büyük mağazalar: "Trendyol, Hepsiburada, Amazon ve n11" ya da (ve_digerleri)
    "Trendyol, Hepsiburada, Amazon, n11 ve diğer mağazalar"."""
    var = [m for m in BUYUK_MAGAZALAR if m in adlar] or list(adlar)[:en_fazla]
    if not var:
        return ""
    if ve_digerleri:
        return ", ".join(var) + " ve diğer mağazalar"
    return (", ".join(var[:-1]) + " ve " + var[-1]) if len(var) > 1 else var[0]


def main():
    if "--gerekirse" in sys.argv and gerek_yok():
        print("SEO · güncel, atlandı")
        return
    bas_zaman = time.time()
    veri, ham = veri_oku()
    guncelleme = int(veri.get("guncelleme") or time.time())
    urunler = [u for u in ham if isinstance(u.get("fiyat"), (int, float)) and u["fiyat"] > 0 and u.get("id") and u.get("baslik")]
    for u in urunler:
        normallestir(u, guncelleme)
    v = surum()
    tv = surum(r"tema\.css\?v=([\w.\-]+)", "")
    d_ = datetime.fromtimestamp(guncelleme, TR)
    ay = f"{AYLAR[d_.month - 1]} {d_.year}"

    def en_buyuk(ls):
        o = max((oran(u) for u in ls), default=0)
        en = next((u for u in ls if oran(u) == o), None) if o > 0 else None
        return en, o

    def dusen_sayisi(ls):
        return sum(1 for u in ls if oran(u) > 0)

    # mağazalar (kategori metinleri için önce sayılır)
    magazalar = {}
    for u in urunler:
        ad = u.get("magaza_ad") or u.get("magaza")
        if ad:
            magazalar.setdefault(ad, []).append(u)
    magaza_sirali = sorted(magazalar.items(), key=lambda x: -len(x[1]))
    magaza_adlari = [ad for ad, _ in magaza_sirali]
    buyukler = magaza_listesi_metni(magaza_adlari, ve_digerleri=True)

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
        en, o = en_buyuk(ls)
        nd = dusen_sayisi(ls)
        giris = (KAT_METIN.get(k, f"{ad} kategorisinde fiyatı gerçekten düşen ürünler.")
                 + f" Şu anda {len(ls)} ürün takipte" + (f", {nd} üründe fiyat düşüşü ölçüldü" if nd else "")
                 + (f"; en büyük düşüş %{o} ile {kisalt(en['baslik'], 70)}." if en else ".")
                 + " Başka mağazada da bulunan ürünlerde en ucuz mağaza ürün sayfasında gösterilir. " + KURAL_KISA)
        kat_sayfa.append({
            "yol": f"/indirimler/{slug(d['ad'])}/", "kisa": ad, "h1": f"{ad} İndirimleri ve En Ucuz Fiyatlar",
            "title": (lambda ek, ad=ad: ilk_uygun([f"{ad} İndirimleri ve En Ucuz Fiyatlar{ek} | {AD}",
                                                   f"{ad} İndirimleri – {ay}{ek} | {AD}",
                                                   f"{ad} İndirimleri{ek} | {AD}"], 70)),
            "aciklama": aciklama_sec(f"{ad} indirimleri ve en ucuz fiyatlar", len(ls), nd, o),
            "giris": giris, "urunler": ls, "ust": [("İndirimler", "/indirimler/")],
        })

    mag_sayfa = []
    for ad, ls in magaza_sirali:
        if len(ls) < MAGAZA_ESIK:
            continue
        ls = sirala(ls)
        en, o = en_buyuk(ls)
        nd = dusen_sayisi(ls)
        mag_sayfa.append({
            "yol": f"/indirimler/{slug(ad)}/", "kisa": ad, "magaza_ad": ad,
            "h1": f"{ad} İndirimleri, Fırsatları ve Kampanyaları",
            "title": (lambda ek, ad=ad: ilk_uygun([f"{ad} İndirimleri, Fırsatları ve Kampanyaları{ek} | {AD}",
                                                   f"{ad} İndirimleri ve Fırsatları{ek} | {AD}",
                                                   f"{ad} İndirimleri{ek} | {AD}"], 70)),
            "aciklama": aciklama_sec(f"{ad} indirimleri, fırsatları ve kampanyaları", len(ls), nd, o),
            "giris": (f"{ad} indirimleri ve fırsatları: {de_eki(ad)} satılan ve {AD} tarafından takip edilen {len(ls)} ürün"
                      + (f"; bunların {nd} tanesinde fiyat düşüşü ölçüldü" if nd else "")
                      + (f", en büyük düşüş %{o}." if o > 0 else ".")
                      + f" Kampanya dönemlerinde fiyatı düşen ürünler de burada görünür. {KURAL_KISA}"
                      + " Fiyat ve stok mağaza sayfasında kontrol edilir."),
            "urunler": ls, "ust": [("İndirimler", "/indirimler/")],
        })

    # özel sayfalar
    kac = kac_sirala([u for u in urunler if u.get("_kac")])
    cok = sorted([u for u in urunler if u.get("cok")], key=lambda u: ((u["cok"].get("s") or 999), -oran(u)))
    ozel = [
        {"yol": "/kacirilmaz-firsatlar/", "kisa": "Kaçırılmaz fırsatlar", "h1": "Kaçırılmaz Fırsatlar: Fiyatı Gerçekten Düşenler",
         "title": f"Kaçırılmaz Fırsatlar – Fiyatı Gerçekten Düşenler | {AD}",
         "aciklama": (f"Kaçırılmaz fırsatlar: {AD}'nun kendi fiyat kayıtlarına göre en az %10 gerçekten düşen "
                      f"{len(kac)} ürün. Üstü çizili fiyat kullanılmaz; en büyük düşüş önce."),
         "giris": ("Fiyatı, ürünün son 90 gün içinde kaydettiğimiz olağan fiyatından (en az 7 günlük geçmişle) en az %10 "
                   "aşağı inen ürünler. Mağazanın üstü çizili fiyatı kullanılmaz. Liste en büyük indirimden küçüğe sıralanır."),
         "urunler": kac},
        {"yol": "/cok-satanlar/", "kisa": "Çok satanlar", "h1": "En Çok Satanlar ve Güncel Fiyatları",
         "title": f"En Çok Satan Ürünler ve Fiyatları, {ay} | {AD}",
         "aciklama": kisalt(f"{buyukler or 'Mağazalar'}: kategori bazlı en çok satan {len(cok)} ürün ve güncel "
                            "fiyatları; fiyat geçmişi ve mağaza karşılaştırmasıyla birlikte.", 160),
         "giris": "Büyük mağazaların kategori bazlı en çok satan ürünleri. Fiyatlar mağaza sayfasından okunur ve ürünün fiyat geçmişiyle karşılaştırılır.",
         "urunler": cok},
    ]
    tum = sirala(list(urunler))
    en, o = en_buyuk(tum)
    nd = dusen_sayisi(tum)
    merkez = {"yol": "/indirimler/", "kisa": "Tüm indirimler", "h1": "Güncel İndirimler ve Fiyatı Düşen Ürünler",
              "title": (lambda ek: ilk_uygun([f"Güncel İndirimler, {ay} – Fiyatı Düşen Ürünler{ek} | {AD}",
                                              f"Güncel İndirimler{ek} | {AD}"], 70)),
              "aciklama": aciklama_sec("Güncel indirimler, kategori ve mağazaya göre", len(tum), nd, o),
              "giris": ((f"{buyukler}da " if buyukler else "") + f"{AD} tarafından takip edilen {len(tum)} ürün"
                        + (f"; {nd} üründe fiyat düşüşü ölçüldü" if nd else "")
                        + (f", en büyük düşüş şu anda %{o}." if o > 0 else ".")
                        + " Aşağıdan kategori ya da mağaza seçerek o bölümün gerçek indirimlerini görebilirsiniz."),
              "urunler": tum}

    # kuponlar
    kuponlar = kuponlari_ayikla(veri, guncelleme)
    kupon_magaza = {}
    for k in kuponlar:
        kupon_magaza.setdefault(k.get("magaza_ad") or k.get("magaza"), []).append(k)
    mag_yol = {s["magaza_ad"]: s["yol"] for s in mag_sayfa}
    kupon_alt = [{"yol": f"/kuponlar/{slug(ad)}/", "kisa": f"{ad} kuponları", "ad": ad} for ad in
                 sorted(kupon_magaza, key=lambda a: -len(kupon_magaza[a]))]
    kupon_ana = {"yol": "/kuponlar/", "kisa": "İndirim kuponları", "h1": "İndirim Kuponları ve Kupon Kodları",
                 "title": f"İndirim Kuponları ve Kupon Kodları, {ay} | {AD}",
                 "aciklama": kisalt(("Güncel indirim kuponları ve kupon kodları: " +
                                     (", ".join(f"{a} ({len(kupon_magaza[a])})" for a in list(kupon_magaza)[:4])
                                      if kuponlar else "şu an doğrulanmış kod yok")
                                     + ". Kodlar paylaşıldığı kampanya sayfasında kontrol edilir, biten kod listeden çıkar."), 160),
                 "giris": (f"{AD}'nun fırsat kanallarından ve forumlardan topladığı, süresi dolmamış mağaza kupon kodları. "
                           "Her kodun yanında paylaşıldığı saat, varsa alt limit, son gün ve kontrol durumu yazar."),
                 "ust": []}

    # bağlantı listeleri
    linkler_kat = [{"yol": s["yol"], "kisa": s["kisa"]} for s in kat_sayfa] + \
                  [{"yol": s["yol"], "kisa": s["kisa"]} for s in ozel]
    linkler_mag = [{"yol": s["yol"], "kisa": s["kisa"]} for s in mag_sayfa] + \
                  [{"yol": "/indirimler/", "kisa": "Tüm indirimler"}, {"yol": "/kuponlar/", "kisa": "İndirim kuponları"}]

    sayfalar = [merkez] + ozel + kat_sayfa + mag_sayfa
    yollar = set()        # liste sayfalarının ilk sayfası
    yazilan = {}          # url → (öncelik)
    for s in sayfalar:
        if s["yol"] in yollar:      # kategori ve mağaza aynı adı taşırsa ikincisi atlanır
            continue
        yollar.add(s["yol"])
        for n in range(1, sayfa_sayisi(s) + 1):
            y = sayfa_yolu(s["yol"], n)
            yaz(y, sayfa_html(s, n, linkler_kat, linkler_mag, guncelleme, v, tv))
            yazilan[y] = "0.8" if n == 1 else "0.4"

    kupon_mag_link = [{"yol": k["yol"], "kisa": k["kisa"]} for k in kupon_alt]
    yaz("/kuponlar/", kupon_sayfasi_html(kupon_ana, kuponlar, linkler_kat, linkler_mag, kupon_mag_link, guncelleme, v, tv))
    yazilan["/kuponlar/"] = "0.7"
    for k in kupon_alt:
        ad = k["ad"]
        n = len(kupon_magaza[ad])
        s = {"yol": k["yol"], "kisa": f"{ad} kuponları", "h1": f"{ad} İndirim Kuponu ve Kupon Kodları",
             "title": ilk_uygun([f"{ad} İndirim Kuponu ve Kupon Kodları, {ay} | {AD}",
                                 f"{ad} İndirim Kuponu ve Kupon Kodları | {AD}", f"{ad} Kupon Kodları | {AD}"], 70),
             "aciklama": kisalt(f"{ad} indirim kuponu ve kupon kodları: şu an {n} kod. Kodlar paylaşıldığı kampanya "
                                f"sayfasında kontrol edilir; biten kod listeden çıkar. {ad} indirimleri de {AD}'da.", 160),
             "giris": (f"{ad} için paylaşılan, süresi dolmamış kupon kodları ({n} kod). Kodun yanında paylaşıldığı saat, "
                       "varsa alt limit, son gün ve kontrol durumu yazar."),
             "ust": [("İndirim kuponları", "/kuponlar/")], "magaza_sayfa": mag_yol.get(ad), "magaza_ad": ad}
        yaz(s["yol"], kupon_sayfasi_html(s, kupon_magaza[ad], linkler_kat, linkler_mag, kupon_mag_link, guncelleme, v, tv))
        yazilan[s["yol"]] = "0.5"

    yaz("/hakkinda/", hakkinda_html([(ad, len(ls)) for ad, ls in magaza_sirali], mag_yol, guncelleme, v, tv,
                                    linkler_kat, linkler_mag))
    yazilan["/hakkinda/"] = "0.6"

    silinen = eskileri_temizle(set(yazilan))

    # sitemap.xml
    lm = iso(guncelleme)
    girdiler = [(SITE + "/", lm, "1.0")] + [(SITE + y, None if y == "/hakkinda/" else lm, pr)
                                            for y, pr in sorted(yazilan.items())] + [(SITE + "/yasal.html", None, "0.2")]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, mod, pr in girdiler:
        sm.append(f"<url><loc>{e(loc)}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + f"<priority>{pr}</priority></url>")
    sm.append("</urlset>")
    sm.append(f"<!-- uretici:{URETICI} -->")
    yaz("sitemap.xml", "\n".join(sm) + "\n")

    # robots.txt: yayin.py'nin sunucudaki ürün klasörüne yazdığıyla aynı (nginx robots.txt'yi oradan sunar)
    yaz("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\nSitemap: {SITE}/u/sitemap.xml\n")

    # IndexNow anahtar dosyası (anahtar herkese açıktır; Bing/Yandex sahipliği bununla doğrular)
    anahtar = str(AYAR.get("indexnow_anahtar") or "").strip().lower()
    if re.fullmatch(r"[a-f0-9]{8,128}", anahtar):
        yaz(f"{anahtar}.txt", anahtar)

    # ana sayfa: öne çıkanlar (sitedeki "Önerilen" sırası; ölçülen düşüşü olanlar önce)
    one_cikan = [u for u in tum if oran(u) > 0][:ONE_CIKAN]
    if len(one_cikan) < ONE_CIKAN:
        secili = {u["id"] for u in one_cikan}
        one_cikan += [u for u in tum if u["id"] not in secili][:ONE_CIKAN - len(one_cikan)]
    ana_sayfa_isle(linkler_kat, linkler_mag, one_cikan, set(magaza_adlari), guncelleme)
    yasal_isle()
    print(f"SEO · {len(yazilan)} sayfa ({len(yollar)} liste) · {len(kuponlar)} kupon · {silinen} eski sayfa silindi · "
          f"{len(urunler)} ürün · güncelleme {tarih_yazi(guncelleme)} · {time.time() - bas_zaman:.1f} sn")


if __name__ == "__main__":
    main()
