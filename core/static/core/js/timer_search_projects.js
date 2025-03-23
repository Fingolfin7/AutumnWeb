$(document).ready(function() {
    $('#pick-subprojects').hide();
    $('#select-all-block').hide();

    let search = $('#project-search');

    // Start the hourglass animation
    animateHourglass();

    // Function to animate the hourglass icon
    function animateHourglass() {
        const hourglassIcon = $('#start-timer i.fa');
        const states = ['fa-hourglass-end', 'fa-hourglass-half', 'fa-hourglass-start'];
        let currentState = 0;

        // Add a CSS class for rotation
        $('<style>')
            .prop('type', 'text/css')
            .html(`
                .rotate-hourglass {
                    transition: transform 1s ease-in-out;
                    transform: rotate(180deg);
                }
                .reset-rotation {
                    transition: none;
                    transform: rotate(0deg);
                }
            `)
            .appendTo('head');

        setInterval(function() {
            // Remove all possible hourglass states
            hourglassIcon.removeClass('fa-hourglass-end fa-hourglass-half fa-hourglass-start');

            // Add the next state
            hourglassIcon.addClass(states[currentState]);

            if (currentState === 2) {
                hourglassIcon.addClass('rotate-hourglass');

                // Reset rotation after the animation completes
                setTimeout(function() {
                    hourglassIcon.removeClass('rotate-hourglass').addClass('reset-rotation');
                    setTimeout(function() {
                        hourglassIcon.removeClass('reset-rotation');
                    }, 50);
                }, 1950); // 50ms before the next state change
            }

            // Move to the next state, or back to the beginning
            currentState = (currentState + 1) % states.length;
        }, 2000); // Change state every 2 seconds
    }

    search.on('keyup',function() {

        let ajax_url = $(this).attr("data-ajax_url");
        let value = $(this).val().trim();

        if (value === "") {
            return;
        }

        $.ajax({
            url: ajax_url,
            type: 'GET',
            data: {
                'search_term': value,
                //'status': 'active'
            },
            dataType: 'json',
            success: function(data){
                let names = data.map(({name}) => name);
                $("#project-search").autocomplete({
                    appendTo: '#project-search-results',
                    source: names,
                    select: function(event, ui) {
                        // Call fillSubprojects when a project is selected
                        fillSubprojects(ui.item.value);
                    }
                });
            }
        });
    });

    // Trigger keyup event on focus so that the autocomplete is displayed
    search.on('focus', function() {
        $(this).trigger('keyup');
    });

    $('#select-all').click(function() {
        let checked = $(this).prop('checked');
        $('input[name="subprojects"]').prop('checked', checked);
    });


    function fillSubprojects(project_name) {
        let url = $("#list_subs").attr("data-ajax_url");
        if (project_name !== "") {
            $('#pick-subprojects').show('slow');
            $('#select-all-block').show('slow');

            $.ajax({
                url: url,
                data: {
                    'project_name': project_name
                },
                dataType: 'json',
                success: function (data) {
                    let options = data.map(({name}) => `
                        <span>
                            <input type="checkbox" name="subprojects" value="${name}" id="${name}">
                            <label for="${name}">${name}</label>
                        </span>

                    `);
                    $('#subproject_options').html(options.join(''));
                }
            })
        }
    }

});
