// Host-a-game form: time options follow the chosen day and urgency.
(function () {
'use strict';
var timeSelect = document.getElementById('id_match_time_slot');
  var allTimeOptions = Array.prototype.slice.call(timeSelect.options).map(function (opt) {
    return { value: opt.value, label: opt.textContent };
  });

  function slotMinutes(value) {
    var parts = value.split(':');
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  }

  function nowMinutes() {
    var d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  }

  function isTomorrowChosen() {
    var choice = document.querySelector('input[name="match_date_choice"]:checked');
    return choice && choice.value === 'TOMORROW';
  }

  function rebuildUrgentOptions() {
    var nowMin = nowMinutes();
    var maxMin = nowMin + 150; // 2.5 hours, half-hour slots
    var current = timeSelect.value;
    timeSelect.innerHTML = '';
    var kept = false;
    allTimeOptions.forEach(function (opt) {
      var m = slotMinutes(opt.value);
      // handle same-day slots only; wrap past midnight is out of scope for "next 2.5h"
      if (m >= nowMin - 30 && m <= maxMin) {
        var el = document.createElement('option');
        el.value = opt.value;
        el.textContent = opt.label;
        if (opt.value === current) kept = true;
        timeSelect.appendChild(el);
      }
    });
    if (!kept && timeSelect.options.length) {
      timeSelect.value = timeSelect.options[0].value;
    }
  }

  function restoreAllOptions() {
    var current = timeSelect.value;
    timeSelect.innerHTML = '';
    allTimeOptions.forEach(function (opt) {
      var el = document.createElement('option');
      el.value = opt.value;
      el.textContent = opt.label;
      timeSelect.appendChild(el);
    });
    timeSelect.value = current;
  }

  function restoreFutureOptionsToday() {
    // "Plan ahead" + "Today": no one can play right now or in the past, so
    // only show slots strictly after the current time.
    var nowMin = nowMinutes();
    var current = timeSelect.value;
    timeSelect.innerHTML = '';
    var kept = false;
    allTimeOptions.forEach(function (opt) {
      if (slotMinutes(opt.value) > nowMin) {
        var el = document.createElement('option');
        el.value = opt.value;
        el.textContent = opt.label;
        if (opt.value === current) kept = true;
        timeSelect.appendChild(el);
      }
    });
    if (!timeSelect.options.length) {
      // Past midnight with nothing left today — fall back to the full list
      // rather than leaving the select empty; the day should really be
      // switched to Tomorrow at this point.
      restoreAllOptions();
      return;
    }
    if (!kept) {
      timeSelect.value = timeSelect.options[0].value;
    }
  }

  function checkCollision() {
    var type = document.querySelector('input[name="match_type"]:checked').value;
    var note = document.getElementById('urgent_collision_note');
    if (type !== 'SCHEDULED' || isTomorrowChosen()) {
      note.classList.add('is-hidden');
      return;
    }
    var nowMin = nowMinutes();
    var maxMin = nowMin + 150;
    var chosenMin = slotMinutes(timeSelect.value);
    note.classList.toggle('is-hidden', !(chosenMin >= nowMin && chosenMin <= maxMin));
  }

  function toggleDateBox() {
    var type = document.querySelector('input[name="match_type"]:checked').value;
    document.getElementById('scheduled_date_box').classList.toggle('is-hidden', type !== 'SCHEDULED');
    document.getElementById('time_helper').textContent = type === 'URGENT'
      ? "Urgent matches must kick off within the next 2.5 hours — half-hour slots."
      : "Pick the exact kickoff time for the day you chose above.";

    if (type === 'URGENT') {
      rebuildUrgentOptions();
    } else if (isTomorrowChosen()) {
      restoreAllOptions();
    } else {
      restoreFutureOptionsToday();
    }
    checkCollision();
  }
  function toggleCostInput() {
    var model = document.getElementById('id_cost_model').value;
    document.getElementById('per_head_box').classList.toggle('is-hidden', model !== 'SPLIT');
  }
  document.querySelectorAll('input[name="match_type"]').forEach(function (el) {
    el.addEventListener('change', toggleDateBox);
  });
  document.querySelectorAll('input[name="match_date_choice"]').forEach(function (el) {
    el.addEventListener('change', toggleDateBox);
  });
  timeSelect.addEventListener('change', checkCollision);
  document.getElementById('id_cost_model').addEventListener('change', toggleCostInput);
  toggleDateBox();
  toggleCostInput();
})();
