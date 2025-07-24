# Description

Web-based time and project tracking software based on [Autumn](https://github.com/Fingolfin7/Autumn). 
This application allows users to manage projects and subprojects, track time spent on various tasks, 
and visualize tracked data over a given period. It includes features such as session history viewing, 
word cloud generation from session notes, and dynamic charting for data visualization. And recently, a 
new Ïnsights" page where you can provide a subset of your session data to an LLM model and ask question about it!

I developed a web based version of the original CLI version to allow users to track their time and projects from anywhere. 
You can import the data from the CLI version and continue tracking projects and time on the web version. 
Data is stored in a SQLite database and can be exported to in JSON format for backup purposes or for importing into the CLI version.

I have deployed the application on PythonAnywhere. You can test it out [here](http://fingolfin7.pythonanywhere.com/).

# Setup

To set up the project locally, follow these steps:

1. **Clone the repository:**
    ```sh
    git clone https://github.com/Fingolfin7/AutumnWeb.git
    cd AutumnWeb
    ```

2. **Create and activate a virtual environment:**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Install the required dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

4. **Apply migrations:**
    ```sh
    python manage.py migrate
    ```

5. **Run the development server:**
    ```sh
    python manage.py runserver
    ```

6. **Access the application:**
    Open your web browser and navigate to `http://127.0.0.1:8000/`.

7. **Create a superuser:**
    To access the admin panel, create a superuser by running.
    ```sh
    python manage.py createsuperuser
    ```
    The admin panel can be accessed at `http://127/0.0.1:8000/admin`.

# Additional Information

- **JavaScript Libraries:** The project uses `Chart.js` for dynamic charting and `wordcloud2.js` for generating word clouds.

# Pages and Screenshots

## Projects Page
(Dark Mode, with bing background images on. Changes everyday with the bing image of the day)
<img width="1885" height="916" alt="image" src="https://github.com/user-attachments/assets/ea91c1d7-4ed5-4891-ab57-36daa2fdde27" />

(Dark Mode, no background image)
<img width="1906" height="908" alt="image" src="https://github.com/user-attachments/assets/9d0f9211-f7c8-4359-91c8-90de571d4c29" />



(Light Mode)
<img width="1891" height="920" alt="image" src="https://github.com/user-attachments/assets/a2c24c0f-ca49-447c-9072-83066797e766" />


## View Sessions History
<img width="1910" height="910" alt="image" src="https://github.com/user-attachments/assets/f79a7097-0f2a-40d5-9190-a71b0bafe65e" />


### Timers Page
<img width="1755" height="848" alt="image" src="https://github.com/user-attachments/assets/2933c467-15cd-4191-befa-5bea096229f3" />


## Insights Page (AI page, load sessions with search as context.)

<img width="1755" height="1131" alt="image" src="https://github.com/user-attachments/assets/a6ae39f0-e972-418a-9989-f3b62c2cd4dd" />



## Visualize Tracked Data Over a given period
![Auutumn Chart Options](https://github.com/user-attachments/assets/382046ca-7a65-46d9-851f-6185738ce2fb)

*Made the gif with [this](https://github.com/Fingolfin7/GIF-Maker)

