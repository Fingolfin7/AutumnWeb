$(document).ready(function() {
    $('#pick-subprojects').hide();
    $('#select-all-block').hide();

    let search = $('#project-search');
    let startButton = $('#start-timer');
    let summary = $('[data-start-timer-summary]');
    let stopAfterAmount = $('#stop-after-amount');
    let stopAfterUnit = $('#stop-after-unit');
    let autoStopEnabled = $('#auto-stop-enabled');
    let lastLoadedProject = '';
    let presetSelectionActive = false;
    let projectIdsByName = {};
    let autocompleteGeneration = 0;
    let subprojectGeneration = 0;
    // A notification can hand us owned ids via the GET page.  They are only
    // used to seed the existing picker; the POST still submits the same names
    // and the server remains the authority for ownership.
    let initialSubprojectIds = String($('[data-reminder-form]').attr('data-initial-subproject-ids') || '')
        .split(',')
        .map(function (value) { return value.trim(); })
        .filter(function (value) { return value !== ''; });
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
        if (!summary.length || !startButton.length) {
            return;
        }

        let projectName = search.val().trim();
        let stopAfterValue = stopAfterAmount.length ? stopAfterAmount.val().trim() : '';
        let stopAfterText = '';

        startButton.prop('disabled', projectName === '');

        if (stopAfterValue !== '' && stopAfterUnit.length) {
            stopAfterText = ` - stops after ${stopAfterValue} ${stopAfterUnit.val()}`;
        }

        summary.text(projectName ? `${projectName}${stopAfterText}` : 'No project selected');
    }

    function maybeFillSubprojects(projectName) {
        projectName = (projectName || search.val()).trim();

        if (projectName === '') {
            subprojectGeneration += 1;
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
        if (!stopAfterAmount.length || !stopAfterUnit.length || !$('.timer-preset-button').length) {
            return;
        }

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

    function updateAutoStopControls() {
        let enabled = autoStopEnabled.length && autoStopEnabled.prop('checked');
        stopAfterAmount.prop('disabled', !enabled);
        stopAfterUnit.prop('disabled', !enabled);
        $('.timer-preset-button').prop('disabled', !enabled);
        if (!enabled) {
            stopAfterAmount.val('');
            presetSelectionActive = false;
            $('.timer-preset-button').removeClass('is-active');
        }
        updateStartTimerSummary();
        document.dispatchEvent(new CustomEvent('autumn:auto-stop-changed'));
    }

    search.on('keyup', function() {
        let ajax_url = $(this).attr('data-ajax_url');
        let value = $(this).val().trim();
        let generation = ++autocompleteGeneration;
        updateStartTimerSummary();

        if (value === '') {
            maybeFillSubprojects('');
            return;
        }

        $.ajax({
            url: ajax_url,
            type: 'GET',
            data: {
                'search': value,
                //'status': 'active'
            },
            dataType: 'json',
            success: function(data) {
                if (generation !== autocompleteGeneration || search.val().trim() !== value) {
                    return;
                }
                let projects = data.projects || [];
                projects.forEach(({id, name}) => {
                    projectIdsByName[name.toLowerCase()] = id;
                });
                let names = projects.map(({name}) => name);
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

    autoStopEnabled.on('change', updateAutoStopControls);

    function resolveProjectId(project_name) {
        // Resolve a typed project name to its id (v2 routes are id-based).
        let cached = projectIdsByName[project_name.toLowerCase()];
        let deferred = $.Deferred();
        if (cached !== undefined) {
            return deferred.resolve(cached).promise();
        }
        $.ajax({
            url: search.attr('data-ajax_url'),
            type: 'GET',
            data: {'search': project_name},
            dataType: 'json',
            success: function(data) {
                let match = (data.projects || []).find(
                    ({name}) => name.toLowerCase() === project_name.toLowerCase()
                );
                if (match) {
                    projectIdsByName[match.name.toLowerCase()] = match.id;
                    deferred.resolve(match.id);
                } else {
                    deferred.reject();
                }
            },
            error: function() {
                deferred.reject();
            }
        });
        return deferred.promise();
    }

    function fillSubprojects(project_name) {
        // data-ajax_url is the v2 route reversed with project_id=0;
        // swap in the real id once the name resolves.
        let urlTemplate = $('#list_subs').attr('data-ajax_url');
        if (project_name !== '') {
            let generation = ++subprojectGeneration;
            lastLoadedProject = project_name;
            $('#pick-subprojects').show('slow');
            $('#select-all-block').show('slow');
            $('#subproject_options').html('<span class="subproject-empty-state">Loading...</span>');

            resolveProjectId(project_name).then(function(projectId) {
                if (generation !== subprojectGeneration || search.val().trim() !== project_name) {
                    return;
                }
                loadSubprojects(
                    urlTemplate.replace('/0/', '/' + projectId + '/'),
                    project_name,
                    generation
                );
            }, function() {
                if (generation !== subprojectGeneration || search.val().trim() !== project_name) {
                    return;
                }
                lastLoadedProject = '';
                $('#subproject_options').html('<span class="subproject-empty-state">Could not load subprojects.</span>');
            });
        }
    }

    function loadSubprojects(url, projectName, generation) {
        $.ajax({
            url: url,
            dataType: 'json',
            success: function(data) {
                if (generation !== subprojectGeneration || search.val().trim() !== projectName) {
                    return;
                }
                let subprojects = data.subprojects || [];
                if (subprojects.length === 0) {
                    $('#subproject_options').html('<span class="subproject-empty-state">No subprojects found.</span>');
                    return;
                }

                let options = subprojects.map(({id, name}, index) => {
                    let optionId = `subproject-option-${index}`;
                    return $('<span>', {class: 'subproject-option'}).append(
                        $('<input>', {
                            type: 'checkbox',
                            name: 'subprojects',
                            value: name,
                            id: optionId,
                            'data-allocation-choice': '',
                            'data-subproject-id': id,
                            'data-subproject-name': name,
                            'data-initial-bp': 0
                        }),
                        $('<label>', {
                            for: optionId,
                            text: name
                        })
                    );
                });
                $('#subproject_options').empty().append(...options);
                initialSubprojectIds.forEach(function (id) {
                    $('#subproject_options input[data-subproject-id="' + id + '"]').prop('checked', true);
                });
            },
            error: function() {
                if (generation !== subprojectGeneration || search.val().trim() !== projectName) {
                    return;
                }
                lastLoadedProject = '';
                $('#subproject_options').html('<span class="subproject-empty-state">Could not load subprojects.</span>');
            }
        });
    }

    updateAutoStopControls();
    renderStopAfterPresets(false);

    let initialProjectId = String($('[data-reminder-form]').attr('data-initial-project-id') || '');
    if (initialProjectId && search.val().trim() !== '') {
        projectIdsByName[search.val().trim().toLowerCase()] = Number(initialProjectId);
        maybeFillSubprojects(search.val().trim());
    }
});
