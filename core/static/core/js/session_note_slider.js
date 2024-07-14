$(document).ready(function () {
    $('.session-note').each(function () {
        var $note = $(this);
        var $container = $note.parent();
        var containerWidth = $container.width();
        var textWidth = $note.width();
        var duration = (textWidth / 250) * 10; // Adjust the speed as needed

        function animateText() {
            $note.css({ left: 0 });
            $note.animate({ left: -textWidth }, duration * 1000, 'linear', function () {
                animateText();
            });
        }

        if (textWidth > containerWidth) {
            animateText();
        }
    });
});
