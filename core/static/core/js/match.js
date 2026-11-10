// Match page: star pickers, "did not attend" lock, and the 20-second withdraw window.
(function () {
  'use strict';

  document.querySelectorAll('.rating-form').forEach(function (form) {
    var wrap = form.querySelector('.st-stars-wrap');
    var buttons = form.querySelectorAll('.st-stars button');
    var value = form.querySelector('input[name=stars]');
    var label = form.querySelector('.star-label');
    var radios = form.querySelectorAll('input[name=showed_up]');
    var last = 5;

    function paint(n) {
      buttons.forEach(function (b) { b.classList.toggle('is-on', +b.dataset.value <= n); });
    }
    function set(n) {
      value.value = n;
      label.textContent = n ? n + (n === 1 ? ' star' : ' stars') : 'No rating for a no-show';
      paint(n);
    }
    buttons.forEach(function (b) {
      b.addEventListener('click', function () { last = +b.dataset.value; set(last); });
    });
    radios.forEach(function (r) {
      r.addEventListener('change', function () {
        if (!r.checked) return;
        var present = r.value === 'on';
        wrap.classList.toggle('is-locked', !present);
        set(present ? last : 0);
      });
    });
    set(5);
  });

  var withdraw = document.getElementById('withdraw');
  if (withdraw) {
    var count = withdraw.querySelector('.count');
    var left = 20;
    count.textContent = '(' + left + 's)';
    var timer = setInterval(function () {
      left -= 1;
      if (left <= 0) { clearInterval(timer); withdraw.hidden = true; return; }
      count.textContent = '(' + left + 's)';
    }, 1000);
  }
})();
