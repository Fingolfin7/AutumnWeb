$(document).ready(function () {
    $('.session-note').each(function () {
        addSlider($(this));
    });
    $('.project-name').each(function (){
        addSlider($(this));
    });

    function addSlider(element) {
        let container = element.parent();
        let containerWidth = container.width();
        let textWidth = element.width();
        let duration = (textWidth / 25); // Adjust the speed as needed

        function animateText() {
            element.css({ left: containerWidth / 2 });
           element.animate({ left: -textWidth }, duration * 1000, 'linear', function () {
                animateText();
            });
        }

        if (textWidth > containerWidth) {
            animateText();
        }
    }
});
