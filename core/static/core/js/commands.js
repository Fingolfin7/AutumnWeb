$(document).ready(function() {
    let run_command = $("#run");
    let output = $("#output");

    let command_dict = {
        'projects': projects,
        'start': start,
    }

    run_command.click(function() {
        // get the command from the input box and send it to the backend. split the command into an array
        // the first element is the command and the rest are the arguments
        let command = $("#command").val();
        let command_array = command.split(" ");
        let command_name = command_array[0];
        let command_args = command_array.slice(1);

        output.append(
            "<p>" +
            "<span class='autumn_tag'>autumn></span> " +
            command +
            "</p>"
        );

        if(command_name in command_dict){
            command_dict[command_name](output, command_args);
        }
        else{
            output.append("<p>Invalid Command: " + command_name + "</p>");
        }

    })
})


