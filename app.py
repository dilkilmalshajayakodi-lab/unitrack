from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'university_secret_key_123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads/medical_reports'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'}

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    index_number = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'administrator', 'admin', or 'student'
    name = db.Column(db.String(100), nullable=False)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_index = db.Column(db.String(20), nullable=False)
    course_code = db.Column(db.String(20), nullable=False)
    date = db.Column(db.Date, default=lambda: datetime.utcnow().date())
    status = db.Column(db.String(10), nullable=False) # 'Present', 'Absent', 'Medical'

class MedicalReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_index = db.Column(db.String(20), nullable=False)
    attendance_id = db.Column(db.Integer, nullable=False) # Link to Attendance record
    date_submitted = db.Column(db.DateTime, default=lambda: datetime.utcnow())
    document_path = db.Column(db.String(255), nullable=False) # Path to uploaded file
    reason = db.Column(db.Text, nullable=True)
    approved = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.String(20), nullable=True) # Admin who approved
    approved_date = db.Column(db.DateTime, nullable=True)

class StudentCourse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_index = db.Column(db.String(20), nullable=False)
    course_code = db.Column(db.String(100), nullable=False)

# --- Setup Helper ---
def create_dummy_data():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(index_number='admin').first():
            # Create Admin
            admin = User(index_number='admin', password=generate_password_hash('admin123'), role='admin', name='System Administrator')
            # Create Student
            student = User(index_number='S1234', password=generate_password_hash('1234'), role='student', name='John Doe')
            db.session.add(admin)
            db.session.add(student)
            db.session.commit()
            print("Database initialized with dummy data.")

# --- Routes ---

@app.route('/')
def home():
    if 'user_id' in session:
        if session['role'] in ['admin', 'administrator']:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        index = request.form['index_number']
        password = request.form['password']
        user = User.query.filter_by(index_number=index).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['role'] = user.role
            session['name'] = user.name
            session['index'] = user.index_number
            return redirect(url_for('home'))
        else:
            flash('Invalid Index Number or Password', 'danger')
            
    return render_template('login.html')

@app.route('/student/dashboard')
def student_dashboard():
    if 'user_id' not in session or session['role'] != 'student':
        return redirect(url_for('login'))
    
    records = Attendance.query.filter_by(student_index=session['index']).order_by(Attendance.date.desc()).all()
    
    # Calculate monthly attendance percentage
    from datetime import datetime as dt
    current_year = dt.now().year
    current_month = dt.now().month
    
    monthly_stats = {}
    
    # Get all unique months from attendance records
    all_records = Attendance.query.filter_by(student_index=session['index']).all()
    months_set = set()
    for record in all_records:
        months_set.add((record.date.year, record.date.month))
    
    for year, month in sorted(months_set, reverse=True):
        month_records = [r for r in all_records if r.date.year == year and r.date.month == month]
        
        present_count = len([r for r in month_records if r.status == 'Present'])
        absent_count = len([r for r in month_records if r.status == 'Absent'])
        medical_count = len([r for r in month_records if r.status == 'Medical'])
        
        total = len(month_records)
        percentage = (present_count / total * 100) if total > 0 else 0
        
        month_name = dt(year, month, 1).strftime('%B %Y')
        monthly_stats[month_name] = {
            'present': present_count,
            'absent': absent_count,
            'medical': medical_count,
            'total': total,
            'percentage': round(percentage, 2)
        }
    
    return render_template('student_dash.html', records=records, name=session['name'], monthly_stats=monthly_stats)

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if 'user_id' not in session or session['role'] not in ['admin', 'administrator']:
        return redirect(url_for('login'))
    
    is_administrator = session['role'] == 'administrator'
    
    # Attendance marking (for both admin and administrator)
    if request.method == 'POST' and 'student_index' in request.form:
        student_idx = request.form['student_index']
        course = request.form['course']
        status = request.form['status']
        date_str = request.form['date']
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        student = User.query.filter_by(index_number=student_idx, role='student').first()
        if not student:
            flash(f'Student {student_idx} not found.', 'danger')
        else:
            new_record = Attendance(student_index=student_idx, course_code=course, status=status, date=date_obj)
            db.session.add(new_record)
            db.session.commit()
            flash('Attendance marked successfully.', 'success')
    
    # User management (only for administrator)
    if is_administrator:
        if request.method == 'POST' and 'add_user' in request.form:
            index = request.form['add_index']
            name = request.form['add_name']
            password = request.form['add_password']
            role = request.form['add_role']
            if User.query.filter_by(index_number=index).first():
                flash('User already exists.', 'danger')
            else:
                user = User(index_number=index, name=name, password=generate_password_hash(password), role=role)
                db.session.add(user)
                db.session.commit()
                flash('User added successfully.', 'success')
        if request.method == 'POST' and 'remove_user' in request.form:
            index = request.form['remove_index']
            user = User.query.filter_by(index_number=index).first()
            if user:
                db.session.delete(user)
                db.session.commit()
                flash('User removed successfully.', 'success')
            else:
                flash('User not found.', 'danger')
        # Export attendance
        if request.method == 'POST' and 'export_attendance' in request.form:
            import csv
            from io import StringIO
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Student Index', 'Date', 'Course', 'Status'])
            for record in Attendance.query.order_by(Attendance.date.desc()).all():
                writer.writerow([record.student_index, record.date, record.course_code, record.status])
            output.seek(0)
            return app.response_class(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment;filename=attendance.csv'}
            )
    
    records = Attendance.query.order_by(Attendance.date.desc()).all()
    users = User.query.order_by(User.role, User.index_number).all()
    
    # Get pending medical reports
    medical_reports_pending = MedicalReport.query.filter_by(approved=False).order_by(MedicalReport.date_submitted.desc()).all()
    
    # Attach attendance object to each medical report for template access
    for report in medical_reports_pending:
        report.attendance_obj = Attendance.query.get(report.attendance_id)
    
    return render_template('admin_dash.html', records=records, users=users, is_administrator=is_administrator, 
                         medical_reports_pending=medical_reports_pending, name=session['name'])

@app.route('/admin/mark-attendance-bulk', methods=['GET', 'POST'])
def mark_attendance_bulk():
    if 'user_id' not in session or session['role'] not in ['admin', 'administrator']:
        return redirect(url_for('login'))
    
    courses = [
        'NANO2112 - Mathematics for Nano Science Technology I',
        'NANO2122 - Fundamentals of Nano-Electronics',
        'NANO2132 - Digital Electronics',
        'NANO2142 - Introduction to Software Development',
        'NANO2151 - Principles of Material Science Engineering',
        'NANO2162 - Engineering Design & Drawings',
        'NANO2172 - Physical Chemistry for Nanotechnology',
        'NANO2182 - Management for Technology',
        'ETCH2111 - English Language & Communication Skills II',
        'PDEV2110 - Career Development II'
    ]
    
    students = []
    selected_course = None
    selected_date = None
    
    if request.method == 'POST':
        # Get course and date from form (always extract these)
        selected_course = request.form.get('course')
        selected_date_str = request.form.get('date')
        
        if selected_course and selected_date_str:
            try:
                selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
                
                # Handle marking attendance for multiple students
                if 'mark_attendance' in request.form:
                    attendance_data = request.form.getlist('attendance[]')
                    student_indices = request.form.getlist('student_index[]')
                    
                    if not student_indices or not attendance_data:
                        flash('No students selected.', 'warning')
                    else:
                        for student_idx, status in zip(student_indices, attendance_data):
                            if status in ['Present', 'Absent']:
                                # Check if record already exists
                                existing = Attendance.query.filter_by(
                                    student_index=student_idx,
                                    course_code=selected_course,
                                    date=selected_date
                                ).first()
                                
                                if existing:
                                    existing.status = status
                                else:
                                    new_record = Attendance(
                                        student_index=student_idx,
                                        course_code=selected_course,
                                        status=status,
                                        date=selected_date
                                    )
                                    db.session.add(new_record)
                        
                        db.session.commit()
                        flash(f'Attendance marked for {selected_course} on {selected_date}', 'success')
                        students = []  # Clear the students list after marking
                        selected_course = None
                        selected_date = None
                else:
                    # Load students for the selected course and date
                    enrolled_students = StudentCourse.query.filter_by(course_code=selected_course).all()
                    
                    if enrolled_students:
                        for enrollment in enrolled_students:
                            student = User.query.filter_by(index_number=enrollment.student_index, role='student').first()
                            if student:
                                # Check if attendance already exists for this student on this date and course
                                existing_attendance = Attendance.query.filter_by(
                                    student_index=student.index_number,
                                    course_code=selected_course,
                                    date=selected_date
                                ).first()
                                students.append({
                                    'index': student.index_number,
                                    'name': student.name,
                                    'status': existing_attendance.status if existing_attendance else 'Present',
                                    'has_record': existing_attendance is not None
                                })
                    else:
                        flash(f'No students enrolled in {selected_course}', 'warning')
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
    
    return render_template('mark_attendance_bulk.html', 
                         courses=courses, 
                         students=students,
                         selected_course=selected_course,
                         selected_date=selected_date)

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        index = request.form['index_number']
        new_password = request.form['new_password']
        user = User.query.filter_by(index_number=index).first()
        if user:
            user.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Password reset successful. Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('User not found.', 'danger')
    return render_template('forgot_password.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        new_name = request.form.get('name')
        new_password = request.form.get('password')
        if new_name:
            user.name = new_name
            session['name'] = new_name
        if new_password:
            user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Profile updated successfully.', 'success')
    return render_template('profile.html', user=user)

@app.route('/admin/bulk-upload', methods=['GET', 'POST'])
def bulk_upload():
    if 'user_id' not in session or session['role'] not in ['admin', 'administrator']:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        course = request.form.get('course')
        file = request.files.get('csv_file')
        
        if not course:
            flash('Please select a course.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        if not file or file.filename == '':
            flash('Please select a CSV file.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file.', 'danger')
            return redirect(url_for('bulk_upload'))
        
        try:
            import csv
            from io import StringIO
            
            # Read the CSV file
            stream = StringIO(file.read().decode('utf8'))
            reader = csv.DictReader(stream)
            
            if not reader.fieldnames or reader.fieldnames != ['student_index', 'date', 'status']:
                flash('CSV must have columns: student_index, date, status', 'danger')
                return redirect(url_for('bulk_upload'))
            
            added_count = 0
            skipped_count = 0
            errors = []
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    student_idx = row['student_index'].strip()
                    date_str = row['date'].strip()
                    status = row['status'].strip()
                    
                    # Validate student exists
                    student = User.query.filter_by(index_number=student_idx, role='student').first()
                    if not student:
                        skipped_count += 1
                        errors.append(f"Row {row_num}: Student {student_idx} not found")
                        continue
                    
                    # Validate status
                    if status not in ['Present', 'Absent']:
                        skipped_count += 1
                        errors.append(f"Row {row_num}: Invalid status '{status}' (must be 'Present' or 'Absent')")
                        continue
                    
                    # Validate date format
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except ValueError:
                        skipped_count += 1
                        errors.append(f"Row {row_num}: Invalid date format '{date_str}' (use YYYY-MM-DD)")
                        continue
                    
                    # Check if record already exists
                    existing = Attendance.query.filter_by(
                        student_index=student_idx,
                        course_code=course,
                        date=date_obj
                    ).first()
                    
                    if existing:
                        skipped_count += 1
                        continue
                    
                    # Add attendance record
                    new_record = Attendance(
                        student_index=student_idx,
                        course_code=course,
                        status=status,
                        date=date_obj
                    )
                    db.session.add(new_record)
                    added_count += 1
                    
                except Exception as e:
                    skipped_count += 1
                    errors.append(f"Row {row_num}: {str(e)}")
            
            db.session.commit()
            
            flash(f'Uploaded {added_count} records successfully for {course}. Skipped {skipped_count} records.', 'success')
            
            if errors and len(errors) <= 10:
                for error in errors:
                    flash(error, 'warning')
            elif errors:
                flash(f'First 10 errors shown. {len(errors) - 10} more errors found.', 'warning')
                for error in errors[:10]:
                    flash(error, 'warning')
            
        except Exception as e:
            flash(f'Error processing CSV file: {str(e)}', 'danger')
        
        return redirect(url_for('bulk_upload'))
    
    return render_template('bulk_upload.html')

@app.route('/student/upload-medical', methods=['GET', 'POST'])
def upload_medical():
    if 'user_id' not in session or session['role'] != 'student':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        attendance_id = request.form.get('attendance_id')
        reason = request.form.get('reason')
        file = request.files.get('document')
        
        if not attendance_id or not file:
            flash('Please select an absence record and upload a document.', 'danger')
            return redirect(url_for('upload_medical'))
        
        if not allowed_file(file.filename):
            flash('Invalid file type. Allowed: PDF, JPG, PNG, DOC, DOCX', 'danger')
            return redirect(url_for('upload_medical'))
        
        try:
            # Get the attendance record
            attendance = Attendance.query.get(int(attendance_id))
            if not attendance or attendance.student_index != session['index'] or attendance.status != 'Absent':
                flash('Invalid attendance record.', 'danger')
                return redirect(url_for('upload_medical'))
            
            # Check if medical report already exists for this record
            existing_report = MedicalReport.query.filter_by(attendance_id=int(attendance_id)).first()
            if existing_report:
                flash('Medical report already submitted for this absence.', 'warning')
                return redirect(url_for('upload_medical'))
            
            # Save the file
            filename = secure_filename(f"{session['index']}_{attendance_id}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Create medical report record
            medical_report = MedicalReport(
                student_index=session['index'],
                attendance_id=int(attendance_id),
                document_path=filepath,
                reason=reason
            )
            db.session.add(medical_report)
            db.session.commit()
            
            flash('Medical report uploaded successfully. Pending admin approval.', 'success')
            return redirect(url_for('upload_medical'))
            
        except Exception as e:
            flash(f'Error uploading medical report: {str(e)}', 'danger')
            return redirect(url_for('upload_medical'))
    
    # Get student's absences that don't have medical reports yet
    student_absences = Attendance.query.filter_by(
        student_index=session['index'],
        status='Absent'
    ).order_by(Attendance.date.desc()).all()
    
    # Filter out absences that already have medical reports
    absence_ids_with_reports = [r.attendance_id for r in MedicalReport.query.filter_by(student_index=session['index']).all()]
    available_absences = [a for a in student_absences if a.id not in absence_ids_with_reports]
    
    # Get medical reports submitted by student
    medical_reports = MedicalReport.query.filter_by(student_index=session['index']).order_by(MedicalReport.date_submitted.desc()).all()
    
    return render_template('upload_medical.html', absences=available_absences, medical_reports=medical_reports)

@app.route('/admin/approve-medical/<int:report_id>', methods=['POST'])
def approve_medical(report_id):
    if 'user_id' not in session or session['role'] not in ['admin', 'administrator']:
        return redirect(url_for('login'))
    
    try:
        report = MedicalReport.query.get(report_id)
        if not report:
            flash('Medical report not found.', 'danger')
            return redirect(url_for('admin_dashboard'))
        
        # Update attendance status to Medical
        attendance = Attendance.query.get(report.attendance_id)
        if attendance:
            attendance.status = 'Medical'
            report.approved = True
            report.approved_by = session['index']
            report.approved_date = datetime.utcnow()
            db.session.commit()
            flash('Medical report approved. Attendance status updated.', 'success')
        else:
            flash('Associated attendance record not found.', 'danger')
    except Exception as e:
        flash(f'Error approving medical report: {str(e)}', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject-medical/<int:report_id>', methods=['POST'])
def reject_medical(report_id):
    if 'user_id' not in session or session['role'] not in ['admin', 'administrator']:
        return redirect(url_for('login'))
    
    try:
        report = MedicalReport.query.get(report_id)
        if not report:
            flash('Medical report not found.', 'danger')
            return redirect(url_for('admin_dashboard'))
        
        db.session.delete(report)
        db.session.commit()
        flash('Medical report rejected.', 'info')
    except Exception as e:
        flash(f'Error rejecting medical report: {str(e)}', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    create_dummy_data() # Run once to set up DB
    app.run(debug=True, host='0.0.0.0', port=5000)