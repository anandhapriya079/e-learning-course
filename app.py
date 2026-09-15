from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from datetime import datetime
import os

from config import Config, allowed_file
from database.db import fetch_one, fetch_all, execute_query
import models.auth as auth_model
import models.course as course_model
import models.assignment as assignment_model
import models.notification as notification_model
import models.ai_helper as ai_model
import models.study_buddy as buddy_model
import models.gamification as gamification_model

app = Flask(__name__)
app.config.from_object(Config)

@app.context_processor
def inject_gamification():
    if session.get('role') == 'student' and session.get('user_id'):
        stats = gamification_model.get_student_stats(session.get('user_id'))
        return dict(game_stats=stats)
    return dict(game_stats=None)

@app.before_request
def update_student_streak():
    if session.get('role') == 'student' and session.get('user_id'):
        try:
            gamification_model.check_and_reset_streak(session.get('user_id'))
        except Exception as e:
            app.logger.error(f"Error checking daily streak: {e}")


# Ensure upload folders exist
MATERIALS_DIR = os.path.join(app.config['UPLOAD_FOLDER'], 'materials')
SUBMISSIONS_DIR = os.path.join(app.config['UPLOAD_FOLDER'], 'submissions')
os.makedirs(MATERIALS_DIR, exist_ok=True)
os.makedirs(SUBMISSIONS_DIR, exist_ok=True)


# ==========================================
# AUTHENTICATION DECORATORS & MIDDLEWARE
# ==========================================

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] not in allowed_roles:
                flash("Unauthorized access. You do not have permissions for this page.", "danger")
                # Redirect to login or their dashboard if logged in
                if 'role' in session:
                    if session['role'] == 'student':
                        return redirect(url_for('student_dashboard'))
                    elif session['role'] == 'faculty':
                        return redirect(url_for('faculty_dashboard'))
                    elif session['role'] == 'admin':
                        return redirect(url_for('admin_dashboard'))
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==========================================
# BASE & AUTHENTICATION ROUTES
# ==========================================

@app.route('/')
def index():
    """Redirect to dashboard if logged in, otherwise to login."""
    if 'role' in session:
        if session['role'] == 'student':
            return redirect(url_for('student_dashboard'))
        elif session['role'] == 'faculty':
            return redirect(url_for('faculty_dashboard'))
        elif session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', '')
        
        user = auth_model.verify_login(email, password, role)
        if user:
            # Set session parameters
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = role
            session['email'] = user['email']
            
            flash(f"Welcome back, {user['name']}!", "success")
            
            if role == 'student':
                return redirect(url_for('student_dashboard'))
            elif role == 'faculty':
                return redirect(url_for('faculty_dashboard'))
            elif role == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid email, password, or role choice. Please try again.", "error")
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        roll_no = request.form.get('roll_no', '').strip()
        department = request.form.get('department', '')
        password = request.form.get('password', '')
        
        student_id = auth_model.register_student(name, email, password, roll_no, department)
        if student_id:
            flash("Registration successful! You can now log in.", "success")
            # Create a registration notification
            notification_model.create_notification('student', student_id, f"Welcome to Cloud LMS! Your student account is successfully registered under roll no {roll_no}.")
            return redirect(url_for('login'))
        else:
            flash("Registration failed. Email or Roll Number may already be in use.", "error")
            
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("You have logged out successfully.", "info")
    return redirect(url_for('login'))


# ==========================================
# STUDENT ROUTES
# ==========================================

@app.route('/student/dashboard')
@login_required
@role_required(['student'])
def student_dashboard():
    student_id = session['user_id']
    search_query = request.args.get('search', '').strip()
    
    student = auth_model.get_user_by_id(student_id, 'student')
    
    # Get courses
    if search_query:
        enrolled_courses = course_model.search_courses(search_query, student_id, enrolled=True)
        available_courses = course_model.search_courses(search_query, student_id, enrolled=False)
    else:
        enrolled_courses = course_model.get_enrolled_courses(student_id)
        available_courses = course_model.get_available_courses(student_id)
        
    # Get pending assignments count across enrolled courses
    pending_count = 0
    for course in enrolled_courses:
        assignments = assignment_model.get_assignments_by_course(course['id'])
        for assign in assignments:
            sub = assignment_model.get_student_submission(assign['id'], student_id)
            if not sub:
                pending_count += 1
                
    # Get notifications
    notifications = notification_model.get_notifications('student', student_id)
    unread_notifications_count = notification_model.get_unread_count('student', student_id)
    
    return render_template(
        'student/dashboard.html',
        active_page='student_dashboard',
        student=student,
        enrolled_courses=enrolled_courses,
        available_courses=available_courses,
        pending_count=pending_count,
        notifications=notifications,
        unread_notifications_count=unread_notifications_count,
        search_query=search_query
    )

@app.route('/student/enroll/<int:course_id>', methods=['POST'])
@login_required
@role_required(['student'])
def student_enroll(course_id):
    student_id = session['user_id']
    if course_model.enroll_student_in_course(student_id, course_id):
        course = course_model.get_course_by_id(course_id)
        flash(f"Successfully enrolled in {course['name']} ({course['code']})!", "success")
        notification_model.create_notification('student', student_id, f"You successfully enrolled in {course['name']} ({course['code']}).")
    else:
        flash("Could not enroll in course.", "error")
    return redirect(url_for('student_dashboard'))

@app.route('/student/unenroll/<int:course_id>', methods=['POST'])
@login_required
@role_required(['student'])
def student_unenroll(course_id):
    student_id = session['user_id']
    course = course_model.get_course_by_id(course_id)
    if course_model.unenroll_student_from_course(student_id, course_id):
        flash(f"Dropped course: {course['name']}.", "info")
    else:
        flash("Could not drop course.", "error")
    return redirect(url_for('student_dashboard'))

@app.route('/student/course/<int:course_id>')
@login_required
@role_required(['student'])
def student_course_detail(course_id):
    student_id = session['user_id']
    
    # Verify student is enrolled in this course
    enrolled = course_model.get_enrolled_courses(student_id)
    is_enrolled = any(c['id'] == course_id for c in enrolled)
    if not is_enrolled:
        flash("You are not enrolled in that course.", "danger")
        return redirect(url_for('student_dashboard'))
        
    course = course_model.get_course_by_id(course_id)
    materials = course_model.get_materials_by_course(course_id)
    
    # Gather assignments and check their submission status
    assignments = assignment_model.get_assignments_by_course(course_id)
    assignments_with_status = []
    for assign in assignments:
        sub = assignment_model.get_student_submission(assign['id'], student_id)
        assignments_with_status.append({
            'assignment': assign,
            'submission': sub
        })
        
    # Get grades
    grades = assignment_model.get_student_grades_by_course(student_id, course_id)
    
    # Get course levels for gamification path
    levels = gamification_model.get_or_generate_course_levels(course_id, course['description'])
    passed_query = "SELECT level_id FROM challenge_results WHERE student_id = %s AND passed = TRUE"
    passed_results = fetch_all(passed_query, (student_id,))
    passed_ids = [r['level_id'] for r in passed_results]
    
    course_levels = []
    is_unlocked = True # Level 1 is always unlocked
    for lvl in levels:
        lvl['is_passed'] = lvl['id'] in passed_ids
        lvl['is_unlocked'] = is_unlocked
        if not lvl['is_passed']:
            is_unlocked = False
        course_levels.append(lvl)
        
    return render_template(
        'student/course_detail.html',
        course=course,
        materials=materials,
        assignments_with_status=assignments_with_status,
        grades=grades,
        course_levels=course_levels
    )

@app.route('/student/assignment/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
@role_required(['student'])
def student_submit_assignment(assignment_id):
    student_id = session['user_id']
    assignment = assignment_model.get_assignment_by_id(assignment_id)
    if not assignment:
        abort(404)
        
    # Verify student is enrolled in the course of this assignment
    enrolled = course_model.get_enrolled_courses(student_id)
    is_enrolled = any(c['id'] == assignment['course_id'] for c in enrolled)
    if not is_enrolled:
        flash("You are not enrolled in this course.", "danger")
        return redirect(url_for('student_dashboard'))
        
    submission = assignment_model.get_student_submission(assignment_id, student_id)
    
    if request.method == 'POST':
        # File upload validation
        if 'file' not in request.files:
            flash("No file part in request.", "error")
            return redirect(request.url)
            
        file = request.files['file']
        if file.filename == '':
            flash("No file selected.", "error")
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            # Save file locally using secure formatted filename
            ext = file.filename.rsplit('.', 1)[1].lower()
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            filename = secure_filename(f"sub_{assignment_id}_std_{student_id}_{timestamp}.{ext}")
            file_path = os.path.join(SUBMISSIONS_DIR, filename)
            file.save(file_path)
            
            # Save submission details in DB
            sub_id = assignment_model.submit_assignment(assignment_id, student_id, filename)
            if sub_id:
                flash("Assignment submitted successfully!", "success")
                # Notify faculty assigned to the course
                course = course_model.get_course_by_id(assignment['course_id'])
                if course['faculty_id']:
                    notification_model.create_notification('faculty', course['faculty_id'], f"Student {session['name']} submitted assignment: '{assignment['title']}' for course '{course['name']}'.")
                return redirect(url_for('student_course_detail', course_id=assignment['course_id']))
            else:
                flash("Could not submit assignment (perhaps it has already been graded).", "error")
        else:
            flash("Invalid file extension. Please check allowed formats.", "error")
            
    return render_template('student/submit_assignment.html', assignment=assignment, submission=submission)

@app.route('/student/ai_assistant')
@login_required
@role_required(['student'])
def student_ai_assistant():
    student_id = session['user_id']
    enrolled_courses = course_model.get_enrolled_courses(student_id)
    course_id = request.args.get('course_id')
    selected_course_id = int(course_id) if course_id else None
    
    return render_template(
        'student/ai_assistant.html',
        active_page='student_ai_assistant',
        enrolled_courses=enrolled_courses,
        selected_course_id=selected_course_id
    )

@app.route('/student/ai_chat', methods=['POST'])
@login_required
@role_required(['student'])
def student_ai_chat():
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    course_id = data.get('course_id', '')
    
    if not message:
        return jsonify({'response': 'Please enter a valid question.'}), 400
        
    course_details = None
    if course_id:
        try:
            course_details = course_model.get_course_by_id(int(course_id))
        except ValueError:
            pass
            
    ai_response = ai_model.ask_ai_assistant(message, course_details)
    return jsonify({'response': ai_response})

@app.route('/student/profile', methods=['GET', 'POST'])
@login_required
@role_required(['student'])
def student_profile():
    student_id = session['user_id']
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            roll_no = request.form.get('roll_no', '').strip()
            department = request.form.get('department', '')
            
            if auth_model.update_profile(student_id, 'student', name, email, department, roll_no):
                session['name'] = name
                session['email'] = email
                flash("Profile updated successfully!", "success")
            else:
                flash("Failed to update profile. Email or Roll Number may already be in use.", "error")
                
        elif action == 'change_password':
            curr_pass = request.form.get('current_password', '')
            new_pass = request.form.get('new_password', '')
            
            if auth_model.change_password(student_id, 'student', curr_pass, new_pass):
                flash("Password changed successfully!", "success")
            else:
                flash("Incorrect current password. Password change failed.", "error")
                
        return redirect(url_for('student_profile'))
        
    student = auth_model.get_user_by_id(student_id, 'student')
    return render_template('student/profile.html', active_page='student_profile', student=student)

@app.route('/student/notifications/read', methods=['POST'])
@login_required
@role_required(['student'])
def student_read_notifications():
    student_id = session['user_id']
    notification_model.mark_all_as_read('student', student_id)
    flash("All notifications marked as read.", "success")
    return redirect(url_for('student_dashboard'))

@app.route('/student/study_buddies')
@login_required
@role_required(['student'])
def student_study_buddies():
    student_id = session['user_id']
    enrolled_courses = course_model.get_enrolled_courses(student_id)
    active_buddies = buddy_model.get_active_buddies(student_id)
    
    # Generate recommendations for each course
    course_recommendations = {}
    for course in enrolled_courses:
        recs = buddy_model.get_recommended_buddies(student_id, course['id'])
        if recs:
            course_recommendations[course['id']] = recs
            
    return render_template(
        'student/study_buddies.html',
        active_page='student_study_buddies',
        enrolled_courses=enrolled_courses,
        course_recommendations=course_recommendations,
        active_buddies=active_buddies
    )

@app.route('/student/add_buddy/<int:course_id>/<int:buddy_id>', methods=['POST'])
@login_required
@role_required(['student'])
def student_add_buddy(course_id, buddy_id):
    student_id = session['user_id']
    if buddy_model.add_buddy(student_id, buddy_id, course_id):
        flash("Successfully paired with study buddy!", "success")
    else:
        flash("Could not add study buddy. You may already be paired.", "error")
    return redirect(url_for('student_study_buddies'))

# ==========================================
# GAMIFICATION & ADVENTURE ROUTES
# ==========================================

@app.route('/student/adventure')
@login_required
@role_required(['student'])
def student_adventure():
    student_id = session['user_id']
    adventure = gamification_model.get_adventure_path(student_id)
    return render_template(
        'student/adventure.html',
        active_page='student_adventure',
        adventure=adventure
    )

@app.route('/student/play_level/<int:level_id>')
@login_required
@role_required(['student'])
def student_play_level(level_id):
    level = fetch_one("""
        SELECT cl.*, c.name as course_title, c.description as course_description 
        FROM course_levels cl 
        JOIN courses c ON cl.course_id = c.id 
        WHERE cl.id = %s
    """, (level_id,))
    
    if not level:
        flash("Level not found.", "error")
        return redirect(url_for('student_adventure'))
        
    # Build course context for AI generation
    materials = fetch_all("SELECT title, description FROM course_materials WHERE course_id = %s", (level['course_id'],))
    materials_context = ", ".join([f"{m['title']}: {m['description']}" for m in materials])
    course_context = f"Course: {level['course_title']}. Description: {level['course_description']}. Level {level['level_number']}: {level['title']}. Details: {level['description']}. Content: {materials_context}"
    
    questions = gamification_model.get_quiz_for_level(level_id, course_context)
    if not questions:
        flash("No questions could be generated. Please try again later.", "warning")
        return redirect(url_for('student_adventure'))
        
    return render_template(
        'student/play_quiz.html',
        active_page='student_adventure',
        level=level,
        questions=questions
    )

@app.route('/student/submit_quiz', methods=['POST'])
@login_required
@role_required(['student'])
def student_submit_quiz():
    student_id = session['user_id']
    level_id = request.form.get('level_id')
    
    level = fetch_one("""
        SELECT cl.*, c.name as course_title, c.description as course_description 
        FROM course_levels cl 
        JOIN courses c ON cl.course_id = c.id 
        WHERE cl.id = %s
    """, (level_id,))
    
    if not level:
        flash("Level not found.", "error")
        return redirect(url_for('student_adventure'))
        
    questions = fetch_all("SELECT * FROM daily_challenges WHERE level_id = %s", (level_id,))
    if not questions:
        flash("Quiz questions not found.", "error")
        return redirect(url_for('student_adventure'))
        
    correct_count = 0
    results = []
    for q in questions:
        submitted = request.form.get(f"question_{q['id']}")
        is_correct = (submitted == q['correct_option'])
        if is_correct:
            correct_count += 1
        results.append({
            'question': q['question'],
            'option_a': q['option_a'],
            'option_b': q['option_b'],
            'option_c': q['option_c'],
            'option_d': q['option_d'],
            'submitted': submitted,
            'correct': q['correct_option'],
            'explanation': q['explanation'],
            'is_correct': is_correct
        })
        
    score_pct = int((correct_count / len(questions)) * 100)
    passed = (score_pct >= 60)
    
    # Award XP
    xp_earned = 10 # Base XP for attempting
    if score_pct == 100:
        xp_earned += 50 # Bonus XP for perfect score
    elif passed:
        xp_earned += 20 # Bonus XP for passing
        
    gamification_model.award_xp(student_id, xp_earned)
    
    # Increment daily streak only if they passed the quiz (>= 60%)
    if passed:
        try:
            gamification_model.increment_daily_streak(student_id)
        except Exception as e:
            app.logger.error(f"Error incrementing daily streak: {e}")
    
    # Record result
    execute_query("DELETE FROM challenge_results WHERE student_id = %s AND level_id = %s", (student_id, level_id))
    execute_query(
        "INSERT INTO challenge_results (student_id, level_id, score, passed) VALUES (%s, %s, %s, %s)",
        (student_id, level_id, score_pct, passed)
    )
    
    # Also record points in the xp_points table for logs
    execute_query(
        "INSERT INTO xp_points (student_id, xp_amount, reason) VALUES (%s, %s, %s)",
        (student_id, xp_earned, f"Completed Level {level['level_number']} Quiz")
    )
    
    # Check badges
    gamification_model.check_and_award_badges(student_id)
    
    return render_template(
        'student/quiz_results.html',
        active_page='student_adventure',
        level=level,
        score=score_pct,
        correct_count=correct_count,
        total_count=len(questions),
        passed=passed,
        xp_earned=xp_earned,
        results=results
    )

@app.route('/student/leaderboard')
@login_required
@role_required(['student'])
def student_leaderboard():
    leaderboard = gamification_model.get_leaderboard()
    return render_template(
        'student/leaderboard.html',
        active_page='student_leaderboard',
        leaderboard=leaderboard
    )



# ==========================================
# FACULTY ROUTES
# ==========================================

@app.route('/faculty/dashboard')
@login_required
@role_required(['faculty'])
def faculty_dashboard():
    faculty_id = session['user_id']
    faculty = auth_model.get_user_by_id(faculty_id, 'faculty')
    courses = course_model.get_courses_by_faculty(faculty_id)
    
    # Calculate statistics for the faculty
    materials_count = 0
    assignments_count = 0
    pending_grading_count = 0
    
    for c in courses:
        # Notes count
        notes = course_model.get_materials_by_course(c['id'])
        materials_count += len(notes)
        # Assignments count
        assigns = assignment_model.get_assignments_by_course(c['id'])
        assignments_count += len(assigns)
        # Submissions pending grading
        for a in assigns:
            subs = assignment_model.get_submissions_by_assignment(a['id'])
            for s in subs:
                if s['status'] == 'Submitted':
                    pending_grading_count += 1
                    
    stats = {
        'materials_count': materials_count,
        'assignments_count': assignments_count,
        'pending_grading_count': pending_grading_count
    }
    
    buddy_stats = buddy_model.get_faculty_buddy_stats(faculty_id)
    
    return render_template(
        'faculty/dashboard.html',
        active_page='faculty_dashboard',
        faculty=faculty,
        courses=courses,
        stats=stats,
        buddy_stats=buddy_stats
    )

@app.route('/faculty/course/create', methods=['POST'])
@login_required
@role_required(['faculty'])
def faculty_create_course():
    faculty_id = session['user_id']
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    
    course_id = course_model.create_course(name, code, description, faculty_id)
    if course_id:
        flash(f"Course '{name}' ({code}) created successfully!", "success")
        # Notify admins
        notification_model.create_notification('admin', None, f"Faculty instructor {session['name']} created a new course: '{name}' ({code}).")
    else:
        flash("Failed to create course. Course code may already exist.", "error")
        
    return redirect(url_for('faculty_dashboard'))

@app.route('/faculty/course/<int:course_id>')
@login_required
@role_required(['faculty'])
def faculty_course_detail(course_id):
    faculty_id = session['user_id']
    course = course_model.get_course_by_id(course_id)
    
    # Verify course belongs to this faculty
    if not course or course['faculty_id'] != faculty_id:
        flash("You are not assigned to manage this course.", "danger")
        return redirect(url_for('faculty_dashboard'))
        
    materials = course_model.get_materials_by_course(course_id)
    assignments = assignment_model.get_assignments_by_course(course_id)
    
    # Get all student submissions for this course's assignments
    submissions = []
    for assign in assignments:
        subs = assignment_model.get_submissions_by_assignment(assign['id'])
        for sub in subs:
            sub['assignment_title'] = assign['title']
            submissions.append(sub)
            
    # Sort submissions by submitted_at desc
    submissions.sort(key=lambda x: x['submitted_at'], reverse=True)
    
    # Pass department list or other parameters
    faculty = auth_model.get_user_by_id(faculty_id, 'faculty')
    
    return render_template(
        'faculty/course_detail.html',
        course=course,
        materials=materials,
        assignments=assignments,
        submissions=submissions,
        faculty=faculty
    )

@app.route('/faculty/course/<int:course_id>/upload_material', methods=['POST'])
@login_required
@role_required(['faculty'])
def faculty_upload_material(course_id):
    faculty_id = session['user_id']
    course = course_model.get_course_by_id(course_id)
    if not course or course['faculty_id'] != faculty_id:
        abort(403)
        
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    
    if 'file' not in request.files:
        flash("No file part.", "error")
        return redirect(url_for('faculty_course_detail', course_id=course_id))
        
    file = request.files['file']
    if file.filename == '':
        flash("No selected file.", "error")
        return redirect(url_for('faculty_course_detail', course_id=course_id))
        
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = secure_filename(f"note_{course_id}_{timestamp}.{ext}")
        file_path = os.path.join(MATERIALS_DIR, filename)
        file.save(file_path)
        
        # Add to DB
        mat_id = course_model.upload_material(course_id, title, description, filename)
        if mat_id:
            flash("Study material uploaded successfully!", "success")
            
            # Send notification to all students enrolled in this course
            enrollments = fetch_all("SELECT student_id FROM enrollments WHERE course_id = %s", (course_id,))
            for enroll in enrollments:
                notification_model.create_notification('student', enroll['student_id'], f"New Study Material: '{title}' uploaded in course '{course['name']}'.")
        else:
            flash("Could not log material details in database.", "error")
    else:
        flash("Invalid file extension.", "error")
        
    return redirect(url_for('faculty_course_detail', course_id=course_id))

@app.route('/faculty/material/delete/<int:material_id>', methods=['POST'])
@login_required
@role_required(['faculty'])
def faculty_delete_material(material_id):
    faculty_id = session['user_id']
    
    # Verify material course is managed by faculty
    material = fetch_one("SELECT * FROM course_materials WHERE id = %s", (material_id,))
    if not material:
        abort(404)
        
    course = course_model.get_course_by_id(material['course_id'])
    if not course or course['faculty_id'] != faculty_id:
        abort(403)
        
    # Delete local file
    try:
        os.remove(os.path.join(MATERIALS_DIR, material['file_path']))
    except OSError as e:
        print(f"Error deleting local material file: {e}")
        
    # Delete from DB
    course_model.delete_material(material_id)
    flash("Study material removed successfully.", "info")
    return redirect(url_for('faculty_course_detail', course_id=course['id']))

@app.route('/faculty/course/<int:course_id>/create_assignment', methods=['POST'])
@login_required
@role_required(['faculty'])
def faculty_create_assignment(course_id):
    faculty_id = session['user_id']
    course = course_model.get_course_by_id(course_id)
    if not course or course['faculty_id'] != faculty_id:
        abort(403)
        
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    due_date_str = request.form.get('due_date', '')
    
    # Parse due_date string (HTML datetime-local format: YYYY-MM-DDTHH:MM)
    try:
        due_date = datetime.strptime(due_date_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        flash("Invalid date format. Assignment creation failed.", "error")
        return redirect(url_for('faculty_course_detail', course_id=course_id))
        
    assign_id = assignment_model.create_assignment(course_id, title, description, due_date)
    if assign_id:
        flash("Assignment published successfully!", "success")
        
        # Notify enrolled students
        enrollments = fetch_all("SELECT student_id FROM enrollments WHERE course_id = %s", (course_id,))
        for enroll in enrollments:
            notification_model.create_notification('student', enroll['student_id'], f"New Assignment Published: '{title}' in course '{course['name']}'. Due: {due_date.strftime('%d-%b %I:%M %p')}.")
    else:
        flash("Failed to save assignment in database.", "error")
        
    return redirect(url_for('faculty_course_detail', course_id=course_id))

@app.route('/faculty/assignment/delete/<int:assignment_id>', methods=['POST'])
@login_required
@role_required(['faculty'])
def faculty_delete_assignment(assignment_id):
    faculty_id = session['user_id']
    assignment = assignment_model.get_assignment_by_id(assignment_id)
    if not assignment:
        abort(404)
        
    # Verify course ownership
    course = course_model.get_course_by_id(assignment['course_id'])
    if not course or course['faculty_id'] != faculty_id:
        abort(403)
        
    # Fetch all submissions for file deletion
    subs = assignment_model.get_submissions_by_assignment(assignment_id)
    for s in subs:
        try:
            os.remove(os.path.join(SUBMISSIONS_DIR, s['file_path']))
        except OSError:
            pass
            
    # Delete from DB
    assignment_model.delete_assignment(assignment_id)
    flash("Assignment deleted successfully.", "info")
    return redirect(url_for('faculty_course_detail', course_id=course['id']))

@app.route('/faculty/submission/grade/<int:submission_id>', methods=['GET', 'POST'])
@login_required
@role_required(['faculty'])
def faculty_grade_submission(submission_id):
    faculty_id = session['user_id']
    submission = assignment_model.get_submission_by_id(submission_id)
    if not submission:
        abort(404)
        
    # Verify faculty teaches the course related to submission
    course = course_model.get_course_by_id(submission['course_id'])
    if not course or course['faculty_id'] != faculty_id:
        abort(403)
        
    if request.method == 'POST':
        score = int(request.form.get('score', 0))
        feedback = request.form.get('feedback', '').strip()
        
        if assignment_model.grade_submission(submission_id, score, feedback, faculty_id):
            flash(f"Submission graded! Score: {score}/100", "success")
            # Notify student
            notification_model.create_notification('student', submission['student_id'], f"Your Submission for '{submission['assignment_title']}' in '{course['name']}' has been graded. Score: {score}/100.")
            return redirect(url_for('faculty_course_detail', course_id=course['id']))
        else:
            flash("Failed to log score/feedback in database.", "error")
            
    return render_template('faculty/grade_submission.html', submission=submission)

@app.route('/faculty/profile', methods=['GET', 'POST'])
@login_required
@role_required(['faculty'])
def faculty_profile():
    faculty_id = session['user_id']
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_profile':
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip()
            
            if auth_model.update_profile(faculty_id, 'faculty', name, email):
                session['name'] = name
                session['email'] = email
                flash("Profile details updated!", "success")
            else:
                flash("Failed to update profile. Email may already be in use.", "error")
                
        elif action == 'change_password':
            curr_pass = request.form.get('current_password', '')
            new_pass = request.form.get('new_password', '')
            
            if auth_model.change_password(faculty_id, 'faculty', curr_pass, new_pass):
                flash("Password updated successfully!", "success")
            else:
                flash("Incorrect current password. Password change failed.", "error")
                
        return redirect(url_for('faculty_profile'))
        
    faculty = auth_model.get_user_by_id(faculty_id, 'faculty')
    return render_template('faculty/profile.html', active_page='faculty_profile', faculty=faculty)


# ==========================================
# ADMIN ROUTES
# ==========================================

@app.route('/admin/dashboard')
@login_required
@role_required(['admin'])
def admin_dashboard():
    # Gather database statistics
    students_count = fetch_one("SELECT COUNT(*) as cnt FROM students")['cnt']
    faculty_count = fetch_one("SELECT COUNT(*) as cnt FROM faculty")['cnt']
    courses_count = fetch_one("SELECT COUNT(*) as cnt FROM courses")['cnt']
    submissions_count = fetch_one("SELECT COUNT(*) as cnt FROM submissions")['cnt']
    
    stats = {
        'students_count': students_count,
        'faculty_count': faculty_count,
        'courses_count': courses_count,
        'submissions_count': submissions_count
    }
    
    # Get courses
    courses = course_model.get_all_courses()
    
    buddy_stats = buddy_model.get_admin_buddy_stats()
    
    return render_template(
        'admin/dashboard.html',
        active_page='admin_dashboard',
        stats=stats,
        courses=courses,
        buddy_stats=buddy_stats
    )

@app.route('/admin/faculty', methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def admin_faculty():
    edit_id = request.args.get('edit_id')
    edit_faculty = None
    if edit_id:
        try:
            edit_faculty = auth_model.get_user_by_id(int(edit_id), 'faculty')
        except ValueError:
            pass
            
    if request.method == 'POST':
        # Add new faculty member
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        department = request.form.get('department', '')
        password = request.form.get('password', '')
        
        fac_id = auth_model.register_faculty(name, email, password, department)
        if fac_id:
            flash("Faculty account created successfully!", "success")
            # Notify newly created faculty member
            notification_model.create_notification('faculty', fac_id, f"Welcome to Cloud LMS! Your instructor account is ready. Department: {department}.")
            return redirect(url_for('admin_faculty'))
        else:
            flash("Failed to create faculty account. Email may already be registered.", "error")
            
    faculty_list = fetch_all("SELECT * FROM faculty ORDER BY name ASC")
    return render_template(
        'admin/faculty.html',
        active_page='admin_faculty',
        faculty_list=faculty_list,
        edit_faculty=edit_faculty
    )

@app.route('/admin/students')
@login_required
@role_required(['admin'])
def admin_students():
    edit_id = request.args.get('edit_id')
    edit_student = None
    if edit_id:
        try:
            edit_student = auth_model.get_user_by_id(int(edit_id), 'student')
        except ValueError:
            pass
            
    students_list = fetch_all("SELECT * FROM students ORDER BY name ASC")
    return render_template(
        'admin/students.html',
        active_page='admin_students',
        students_list=students_list,
        edit_student=edit_student
    )

@app.route('/admin/user/edit/<string:role>/<int:user_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_edit_user(role, user_id):
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    
    if role == 'student':
        roll_no = request.form.get('roll_no', '').strip()
        department = request.form.get('department', '')
        success = auth_model.update_profile(user_id, 'student', name, email, department, roll_no)
        redirect_url = url_for('admin_students')
    elif role == 'faculty':
        department = request.form.get('department', '')
        success = auth_model.update_profile(user_id, 'faculty', name, email, department)
        redirect_url = url_for('admin_faculty')
    else:
        abort(400)
        
    if success:
        flash(f"Account for {name} updated successfully.", "success")
    else:
        flash("Failed to update profile parameters. Check email/roll constraints.", "error")
        
    return redirect(redirect_url)

@app.route('/admin/user/delete/<string:role>/<int:user_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_delete_user(role, user_id):
    table = ""
    if role == 'student':
        table = 'students'
        redirect_url = url_for('admin_students')
    elif role == 'faculty':
        table = 'faculty'
        redirect_url = url_for('admin_faculty')
    else:
        abort(400)
        
    # Check if delete is possible
    try:
        execute_query(f"DELETE FROM {table} WHERE id = %s", (user_id,))
        flash("User account deleted permanently.", "info")
    except Exception as e:
        print(f"Error deleting user: {e}")
        flash("Database constraint error. Could not delete user account.", "error")
        
    return redirect(redirect_url)

@app.route('/admin/courses', methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def admin_courses():
    edit_id = request.args.get('edit_id')
    edit_course = None
    if edit_id:
        try:
            edit_course = course_model.get_course_by_id(int(edit_id))
        except ValueError:
            pass
            
    if request.method == 'POST':
        # Add new course
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip()
        description = request.form.get('description', '').strip()
        faculty_id = request.form.get('faculty_id')
        
        # Map blank string to None for SQL null values
        fac_id = int(faculty_id) if faculty_id else None
        
        course_id = course_model.create_course(name, code, description, fac_id)
        if course_id:
            flash(f"Course '{name}' ({code}) published successfully!", "success")
            
            # Send notification to assigned faculty
            if fac_id:
                notification_model.create_notification('faculty', fac_id, f"Admin assigned you as course instructor for: {name} ({code}).")
                
            return redirect(url_for('admin_courses'))
        else:
            flash("Failed to create course. Course code may already exist.", "error")
            
    courses = course_model.get_all_courses()
    faculty_list = fetch_all("SELECT * FROM faculty ORDER BY name ASC")
    
    return render_template(
        'admin/courses.html',
        active_page='admin_courses',
        courses=courses,
        faculty_list=faculty_list,
        edit_course=edit_course
    )

@app.route('/admin/courses/edit/<int:course_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_edit_course(course_id):
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    faculty_id = request.form.get('faculty_id')
    
    fac_id = int(faculty_id) if faculty_id else None
    
    # Get previous faculty_id for notification checks
    prev_course = course_model.get_course_by_id(course_id)
    
    if course_model.update_course(course_id, name, code, description, fac_id):
        flash("Course parameters updated successfully.", "success")
        
        # Send assignment notifications if faculty changed
        if fac_id and (not prev_course or prev_course['faculty_id'] != fac_id):
            notification_model.create_notification('faculty', fac_id, f"Admin assigned you as course instructor for: {name} ({code}).")
    else:
        flash("Failed to update course parameters. Code may be in use.", "error")
        
    return redirect(url_for('admin_courses'))

@app.route('/admin/courses/delete/<int:course_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_delete_course(course_id):
    course = course_model.get_course_by_id(course_id)
    
    # Fetch all materials and submissions linked to this course to delete local files
    materials = course_model.get_materials_by_course(course_id)
    for m in materials:
        try:
            os.remove(os.path.join(MATERIALS_DIR, m['file_path']))
        except OSError:
            pass
            
    assignments = assignment_model.get_assignments_by_course(course_id)
    for assign in assignments:
        subs = assignment_model.get_submissions_by_assignment(assign['id'])
        for s in subs:
            try:
                os.remove(os.path.join(SUBMISSIONS_DIR, s['file_path']))
            except OSError:
                pass
                
    if course_model.delete_course(course_id):
        flash(f"Course '{course['name']}' deleted successfully.", "info")
    else:
        flash("Could not delete course from database.", "error")
        
    return redirect(url_for('admin_courses'))


# ==========================================
# DATABASE AUTO-SEEDER FUNCTION
# ==========================================

def seed_database():
    """
    Checks if there's any admin. If not, seeds a default admin.
    """
    try:
        admin = fetch_one("SELECT * FROM admins LIMIT 1")
        if not admin:
            hashed_pw = generate_password_hash("adminpassword")
            execute_query(
                "INSERT INTO admins (name, email, password_hash) VALUES (%s, %s, %s)",
                ("System Admin", "admin@lms.com", hashed_pw)
            )
            print("[AUTO-SEEDER] Created default admin login: admin@lms.com / adminpassword")
    except Exception as e:
        print(f"[AUTO-SEEDER WARNING] Database seeding checks skipped. Ensure MySQL is running and schema.sql is imported. Error details: {e}")

# Call seeder on startup
#seed_database()


if __name__ == '__main__':
    # Running locally on port 5000
    app.run(debug=True, host='127.0.0.1', port=5000)
