$(document).ready(function () {
    $('.session-note').each(function () {
        addSlider($(this));
    });
    // $('.project-name-slider').each(function (){
    //     addSlider($(this));
    //     console.log($(this));
    // });

    function addSlider(element) {
        let container = element.closest('.session-note-slider');
        if (!container.length) {
            container = element.parent();
        }
        let containerWidth = container.width();
        let textWidth = element.width();
        let duration = (textWidth / 25); // Adjust the speed as needed

        function animateText() {
            element.css({ position: 'relative' });
            element.css({ left: containerWidth / 2 });
            element.animate({ left: -textWidth }, duration * 1000, 'linear', function () {
                animateText();
            });
        }



        if (textWidth > containerWidth) {
            animateText();
            console.log(textWidth);
            console.log(containerWidth);
        }
    }
});
