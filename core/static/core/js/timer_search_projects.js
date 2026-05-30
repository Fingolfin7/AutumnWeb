$(document).ready(function() {
    $('#pick-subprojects').hide();
    $('#select-all-block').hide();

    let search = $('#project-search');
    let startButton = $('#start-timer');
    let summary = $('[data-start-timer-summary]');
    let stopAfterAmount = $('#stop-after-amount');
    let stopAfterUnit = $('#stop-after-unit');
    let lastLoadedProject = '';
    let presetSelectionActive = false;
    const stopAfterPresets = {
        minutes: [
            {value: '15', label: '15m'},
            {value: '25', label: '25m'},
            {value: '30', label: '30m'},
            {value: '45', label: '45m'},
            {value: '60', label: '60m'}
        ],
        hours: [
            {value: '1', label: '1h'},
            {value: '2', label: '2h'},
            {value: '3', label: '3h'},
            {value: '4', label: '4h'},
            {value: '8', label: '8h'}
        ]
    };

    function updateStartTimerSummary() {
        let projectName = search.val().trim();
        let stopAfterValue = stopAfterAmount.val().trim();
        let stopAfterText = '';

        startButton.prop('disabled', projectName === '');

        if (stopAfterValue !== '') {
            stopAfterText = ` - stops after ${stopAfterValue} ${stopAfterUnit.val()}`;
        }

        summary.text(projectName ? `${projectName}${stopAfterText}` : 'No project selected');
    }

    function maybeFillSubprojects(projectName) {
        projectName = (projectName || search.val()).trim();

        if (projectName === '') {
            lastLoadedProject = '';
            $('#pick-subprojects').hide('fast');
            $('#select-all-block').hide('fast');
            $('#subproject_options').empty();
            return;
        }

        if (projectName === lastLoadedProject) {
            return;
        }

        fillSubprojects(projectName);
    }

    function renderStopAfterPresets(selectDefault) {
        let presets = stopAfterPresets[stopAfterUnit.val()] || stopAfterPresets.minutes;
        let activeValue = stopAfterAmount.val().trim();

        if (selectDefault) {
            activeValue = presets[0].value;
            stopAfterAmount.val(activeValue);
        }

        $('.timer-preset-button').each(function(index) {
            let preset = presets[index];

            $(this)
                .toggle(Boolean(preset))
                .toggleClass('is-active', Boolean(preset) && preset.value === activeValue)
                .data('stop-after-preset', preset ? preset.value : '')
                .text(preset ? preset.label : '');
        });
    }

    search.on('keyup', function() {
        let ajax_url = $(this).attr('data-ajax_url');
        let value = $(this).val().trim();
        updateStartTimerSummary();

        if (value === '') {
            maybeFillSubprojects('');
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
            success: function(data) {
                let names = data.map(({name}) => name);
                $('#project-search').autocomplete({
                    appendTo: '#project-search-results',
                    source: names,
                    select: function(event, ui) {
                        search.val(ui.item.value);
                        updateStartTimerSummary();
                        maybeFillSubprojects(ui.item.value);
                    }
                });
            }
        });
    });

    search.on('keydown', function(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            maybeFillSubprojects();
        }
    });

    // Trigger keyup event on focus so that the autocomplete is displayed
    search.on('focus', function() {
        $(this).trigger('keyup');
    });

    search.on('change blur', function() {
        updateStartTimerSummary();
        maybeFillSubprojects();
    });

    $('#select-all').click(function() {
        let checked = $(this).prop('checked');
        $('input[name="subprojects"]').prop('checked', checked);
    });

    $('.timer-preset-button').on('click', function() {
        presetSelectionActive = true;
        $('.timer-preset-button').removeClass('is-active');
        $(this).addClass('is-active');
        stopAfterAmount.val($(this).data('stop-after-preset'));
        updateStartTimerSummary();
    });

    stopAfterAmount.on('input', function() {
        presetSelectionActive = false;
        $('.timer-preset-button').removeClass('is-active');
        updateStartTimerSummary();
    });

    stopAfterUnit.on('change', function() {
        renderStopAfterPresets(presetSelectionActive);
        updateStartTimerSummary();
    });

    function fillSubprojects(project_name) {
        let url = $('#list_subs').attr('data-ajax_url');
        if (project_name !== '') {
            lastLoadedProject = project_name;
            $('#pick-subprojects').show('slow');
            $('#select-all-block').show('slow');
            $('#subproject_options').html('<span class="subproject-empty-state">Loading...</span>');

            $.ajax({
                url: url,
                data: {
                    'project_name': project_name
                },
                dataType: 'json',
                success: function(data) {
                    if (data.length === 0) {
                        $('#subproject_options').html('<span class="subproject-empty-state">No subprojects found.</span>');
                        return;
                    }

                    let options = data.map(({name}, index) => {
                        let optionId = `subproject-option-${index}`;
                        return $('<span>', {class: 'subproject-option'}).append(
                            $('<input>', {
                                type: 'checkbox',
                                name: 'subprojects',
                                value: name,
                                id: optionId
                            }),
                            $('<label>', {
                                for: optionId,
                                text: name
                            })
                        );
                    });
                    $('#subproject_options').empty().append(...options);
                },
                error: function() {
                    lastLoadedProject = '';
                    $('#subproject_options').html('<span class="subproject-empty-state">Could not load subprojects.</span>');
                }
            });
        }
    }

    updateStartTimerSummary();
    renderStopAfterPresets(false);
});
