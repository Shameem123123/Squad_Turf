// SquadTurf — shared front-end behaviour

document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss toasts after a few seconds.
  document.querySelectorAll('.toast').forEach(function (toast, i) {
    setTimeout(function () {
      toast.style.transition = 'opacity 0.3s ease';
      toast.style.opacity = '0';
      setTimeout(function () { toast.remove(); }, 300);
    }, 5000 + i * 400);
  });
});
