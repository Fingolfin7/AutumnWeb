$(document).ready(function() {
    $('#pick-subprojects').hide();
    $('#select-all-block').hide();

    let search = $('#project-search');

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
                        updateCreateSubprojectsLink(ui.item.value);
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


    function updateCreateSubprojectsLink(project_name) {
        let createSubprojectsLink = $('#create-subproject-link');
        let url = createSubprojectsLink.data('base-url');
        url = url.replace('PROJECT_NAME', project_name);

        let createSubprojectsButton = $('#create-subproject-button');
        createSubprojectsButton.on('click', function() {
            window.location.href = url;
        });

        createSubprojectsButton.show('slow');
    }
});
