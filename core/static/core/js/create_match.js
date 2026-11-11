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
      // Only slots still to come: at 11:25 the first choice is 11:30, never 11:00.
      if (m > nowMin && m <= maxMin) {
        var el = document.createElement('option');
        el.value = opt.value;
        el.textContent = opt.label;
        if (opt.value === current) kept = true;
        timeSelect.appendChild(el);
      }
    });
    if (timeSelect.options.length) {
      timeSelect.value = kept ? current : timeSelect.options[0].value;
    }
    setNoSlots(!timeSelect.options.length,
      "No slots left in the next 2.5 hours. Choose Plan ahead \u2192 Tomorrow.");
  }

  // Nothing left to pick: say so and keep Post disabled instead of failing on submit.
  function setNoSlots(none, message) {
    var submit = document.querySelector('.st-form-card button[type="submit"]');
    if (submit) submit.disabled = none;
    if (none) document.getElementById('time_helper').textContent = message;
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
      // Nothing left today: move to Tomorrow, where every slot is still ahead.
      var tomorrow = document.querySelector('input[name="match_date_choice"][value="TOMORROW"]');
      if (tomorrow) tomorrow.checked = true;
      restoreAllOptions();
      return;
    }
    timeSelect.value = kept ? current : timeSelect.options[0].value;
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
    setNoSlots(false, '');

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
