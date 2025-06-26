# FURsvp Event Manager

FURsvp is a Django-based event management system designed to help organizers within the furry fandom manage events, RSVPs, and user interactions. It provides a streamlined platform for event creation, attendee tracking, and administrative oversight.

## Features

*   **User Authentication & Profiles**
    *   Secure user registration, login, and logout.
    *   Custom user profiles with display names, Discord, and Telegram username fields.
    *   Profile picture upload and management.

*   **Event Management**
    *   Intuitive event creation form (title, associated group, date, and description).
    *   Detailed event pages displaying event information and attendee RSVPs.
    *   Ability for event organizers and administrators to delete events.
    *   Home page displays upcoming events in a modern card layout, sorted by date with an option to sort by group.

*   **RSVP System**
    *   Users can easily RSVP to events with 'Attending', 'Maybe', or 'Not Attending' statuses.
    *   Organizers can view RSVP lists, categorized by response.

*   **Group Management**
    *   Admins can create, rename, and delete event groups.

*   **Administration & Permissions**
    *   Site administrators can promote users to 'Approved Group Administrator' status.
    *   Approved Group Administrators can create events for their assigned groups.
    *   Delegated assistant functionality allows organizers to assign other users to manage specific groups.
    *   **User Ban System**: Organizers and administrators can ban users from specific groups or from all events hosted by that organizer. Banned users are prevented from RSVPing to relevant events.
    *   **Unban Functionality**: Administrators have a dedicated section in the profile tab to view all banned users and unban them.
    *   Contact information (Discord, Telegram) of attendees is visible to event organizers, site administrators, and delegated assistants via a modal.

## Installation

To set up the FURsvp Event Manager locally, follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd FursVP
    ```

2.  **Create a virtual environment and activate it:**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up your database:**
    ```bash
    python manage.py makemigrations
    python manage.py migrate
    ```

5.  **Create a superuser (for administrative access):**
    ```bash
    python manage.py createsuperuser
    ```

6.  **Run the development server:**
    ```bash
    python manage.py runserver
    ```

    The application will be accessible at `http://127.0.0.1:8000/`.

## Usage

*   **Register an Account**: Navigate to `/accounts/register/` to create a new user account.
*   **Login**: Access `/accounts/login/` to log in.
*   **Create Events**: If you are an 'Approved Group Administrator', you can create events via the 'Create Event' link in the navigation bar.
*   **RSVP to Events**: Browse upcoming events on the home page and RSVP to participate.
*   **Administration**: Superusers can access `/accounts/administration/` to manage users, groups, and ban lists.

## Contributing

Contributions are welcome! If you have suggestions for improvements or find any issues, please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details. 