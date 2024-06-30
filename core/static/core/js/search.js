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
                        // Call fill_subprojects when a project is selected
                        fill_subprojects(ui.item.value);
                    }
                });
            }
        });
    });

    // Trigger keyup event on focus so that the autocomplete is displayed
    search.on('focus', function() {
        $(this).trigger('keyup');
    });


    function fill_subprojects(project_name) {
        let url = $("#list_subs").attr("data-ajax_url");;
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

    $('#select-all').click(function() {
        let checked = $(this).prop('checked');
        $('input[name="subprojects"]').prop('checked', checked);
    });
});
