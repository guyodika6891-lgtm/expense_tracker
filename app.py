import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_bcrypt import Bcrypt
from models import db, User, Expense
from datetime import datetime, date
from functools import wraps
from dotenv import load_dotenv
from sqlalchemy import func

load_dotenv()


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback-key-change-me')


app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///expenses.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db.init_app(app)
bcrypt = Bcrypt(app)


with app.app_context():
    db.create_all()
    print("✅ Expense Tracker database created successfully!")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ============================================
# HOME ROUTE (Dashboard)
# ============================================
@app.route('/')
def index():
    if not session.get('logged_in'):
        return render_template('index.html', expenses=None)

    user_id = session['user_id']

    # Recent expenses (10 latest)
    expenses = Expense.query.filter_by(user_id=user_id).order_by(
        Expense.date.desc(),
        Expense.created_at.desc()
    ).limit(10).all()

    # ---- Dashboard stats ----
    today = date.today()
    first_of_month = date(today.year, today.month, 1)

    # Total spent this month
    month_total = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == user_id,
        Expense.date >= first_of_month
    ).scalar() or 0

    # Count of expenses this month
    month_count = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.date >= first_of_month
    ).count()

    # All-time total
    all_time_total = db.session.query(func.sum(Expense.amount)).filter(
        Expense.user_id == user_id
    ).scalar() or 0

    # Spending by category this month
    category_data = db.session.query(
        Expense.category,
        func.sum(Expense.amount)
    ).filter(
        Expense.user_id == user_id,
        Expense.date >= first_of_month
    ).group_by(Expense.category).all()

    categories = [c[0] for c in category_data]
    amounts = [float(c[1]) for c in category_data]

    return render_template(
        'index.html',
        expenses=expenses,
        month_total=month_total,
        month_count=month_count,
        all_time_total=all_time_total,
        categories=categories,
        amounts=amounts
    )


   

# ============================================
# AUTHENTICATION ROUTES
# ============================================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters')
        elif User.query.filter_by(username=username).first():
            errors.append('This username is already taken')

        if not email or '@' not in email or '.' not in email:
            errors.append('Please enter a valid email')
        elif User.query.filter_by(email=email).first():
            errors.append('This email is already registered')

        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters')

        if password != confirm_password:
            errors.append('Passwords do not match')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html', username=username, email=email)

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(username=username, email=email, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = User.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['logged_in'] = True

            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'error')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('profile.html', user=user)



@app.route('/expense/new', methods=['GET', 'POST'])
@login_required
def new_expense():
    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        date_str = request.form.get('date', '').strip()

        errors = []
        try:
            amount = float(amount)
            if amount <= 0:
                errors.append('Amount must be greater than 0')
        except ValueError:
            errors.append('Please enter a valid amount')

        if not category:
            errors.append('Category is required')

        # Parse date
        expense_date = None
        if date_str:
            try:
                expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append('Invalid date format')
        else:
            errors.append('Date is required')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('new_expense.html',
                                 amount=amount,
                                 category=category,
                                 description=description,
                                 date=date_str)

        expense = Expense(
            amount=amount,
            category=category,
            description=description,
            date=expense_date,
            user_id=session['user_id']
        )
        db.session.add(expense)
        db.session.commit()

        flash('Expense added successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('new_expense.html')


@app.route('/expense/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.user_id != session['user_id']:
        flash('You can only edit your own expenses.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        amount = request.form.get('amount', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        date_str = request.form.get('date', '').strip()

        errors = []
        try:
            amount = float(amount)
            if amount <= 0:
                errors.append('Amount must be greater than 0')
        except ValueError:
            errors.append('Please enter a valid amount')

        if not category:
            errors.append('Category is required')

        expense_date = None
        if date_str:
            try:
                expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                errors.append('Invalid date format')
        else:
            errors.append('Date is required')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('edit_expense.html', expense=expense)

        expense.amount = amount
        expense.category = category
        expense.description = description
        expense.date = expense_date
        db.session.commit()

        flash('Expense updated successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('edit_expense.html', expense=expense)


@app.route('/expense/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete_expense(expense_id):
    expense = Expense.query.get_or_404(expense_id)
    if expense.user_id != session['user_id']:
        flash('You can only delete your own expenses.', 'error')
        return redirect(url_for('index'))

    db.session.delete(expense)
    db.session.commit()

    flash('Expense deleted successfully!', 'info')
    return redirect(url_for('index'))

@app.route('/expenses')
@login_required
def all_expenses():
    user_id = session['user_id']
    month = request.args.get('month', '').strip()
    category = request.args.get('category', '').strip()

    query = Expense.query.filter_by(user_id=user_id)

    # Month filter
    if month:
        try:
            year, m = map(int, month.split('-'))
            start = date(year, m, 1)
            # End of month
            if m == 12:
                end = date(year + 1, 1, 1)
            else:
                end = date(year, m + 1, 1)
            query = query.filter(Expense.date >= start, Expense.date < end)
        except (ValueError, AttributeError):
            flash('Invalid month format', 'error')

    # Category filter
    if category:
        query = query.filter_by(category=category)

    expenses = query.order_by(Expense.date.desc()).all()

    # Get all distinct categories for the filter dropdown
    categories = db.session.query(Expense.category).filter_by(
        user_id=user_id
    ).distinct().all()
    categories = [c[0] for c in categories]

    # Compute total of filtered results
    filtered_total = sum(e.amount for e in expenses)

    return render_template(
        'expenses.html',
        expenses=expenses,
        month=month,
        category=category,
        categories=categories,
        filtered_total=filtered_total
    )


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    app.run(debug=True)