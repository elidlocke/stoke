// The site's motion: elements marked data-reveal fade up as they scroll into view, once; and the hero's
// [data-typed] phrase types out each of its data-words in turn. Loaded from <head> without defer, so content is
// hidden (html.motion) before the first paint. A file rather than an inline script, for the
// Content-Security-Policy in render.yaml. Without JavaScript, or with reduced motion, everything just shows.
;(function () {
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced || !('IntersectionObserver' in window)) return
  document.documentElement.classList.add('motion')

  function reveal() {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (!e.isIntersecting) return
          e.target.classList.add('in')
          observer.unobserve(e.target)
        })
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.1 },
    )
    document.querySelectorAll('[data-reveal]').forEach(function (el) {
      observer.observe(el)
    })
  }

  function type(el) {
    var words = (el.getAttribute('data-words') || '').split('|').filter(Boolean)
    if (words.length < 2) return
    var word = 0
    var shown = words[0].length
    var deleting = false

    function tick() {
      var target = words[word]
      if (!deleting && shown < target.length) {
        shown++
        el.textContent = target.slice(0, shown)
        return setTimeout(tick, 70)
      }
      if (!deleting) {
        deleting = true
        return setTimeout(tick, 1800) // hold the full phrase
      }
      if (shown > 0) {
        shown--
        el.textContent = target.slice(0, shown)
        return setTimeout(tick, 35)
      }
      deleting = false
      word = (word + 1) % words.length
      setTimeout(tick, 250)
    }
    setTimeout(function () {
      deleting = true
      tick()
    }, 2200) // the first phrase is already showing
  }

  document.addEventListener('DOMContentLoaded', function () {
    reveal()
    document.querySelectorAll('[data-typed]').forEach(type)
  })
})()
