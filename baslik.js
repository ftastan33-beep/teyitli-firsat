/* Düşero · masaüstünde büyük başlık ekrandan çıkınca küçük başlığı üstten kaydırarak gösterir.
   Küçülme anında başlığın yerine aynı yükseklikte yer tutucu konur; sayfa kaymaz. En üste dönünce eski hâline gelir. */
(function () {
  var mq = window.matchMedia("(min-width:900px)"), ust = document.querySelector(".ust");
  if (!ust) return;
  var bos = document.createElement("div"); bos.setAttribute("aria-hidden", "true");
  ust.parentNode.insertBefore(bos, ust);
  var kucuk = false, bekliyor = false, alt = 0, yanlar = document.querySelectorAll(".yan-ic");
  /* Kenar kutularını (Filtreler, Kampanya takvimi) küçük başlığın altına hizalar; yalnızca bu kutular etkilenir */
  function yanAyar(h) {
    for (var i = 0; i < yanlar.length; i++) {
      yanlar[i].style.top = h ? (h + 18) + "px" : "";
      yanlar[i].style.maxHeight = h ? "calc(100vh - " + (h + 36) + "px)" : "";
    }
  }
  function ac() {
    bos.style.height = ust.offsetHeight + "px";
    ust.classList.add("ust-kucuk"); kucuk = true;
    requestAnimationFrame(function () { if (kucuk) yanAyar(ust.offsetHeight); });
  }
  function kapat() { ust.classList.remove("ust-kucuk"); bos.style.height = ""; kucuk = false; yanAyar(0); }
  function ayarla() {
    bekliyor = false;
    if (!mq.matches) { if (kucuk) kapat(); return; }
    var y = window.scrollY;
    if (!kucuk) {
      alt = ust.getBoundingClientRect().bottom + y;
      if (y > alt + 24) ac();
    } else if (y < alt) kapat();
  }
  window.addEventListener("scroll", function () { if (!bekliyor) { bekliyor = true; requestAnimationFrame(ayarla); } }, { passive: true });
  var zz; window.addEventListener("resize", function () { clearTimeout(zz); zz = setTimeout(function () { if (kucuk) kapat(); ayarla(); }, 150); }, { passive: true });
  ayarla();
})();
