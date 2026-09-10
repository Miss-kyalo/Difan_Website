from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Driver(db.Model):
    __tablename__ = 'drivers'

    id = db.Column(db.Integer, primary_key=True)
    driver_code = db.Column(db.String(20), unique=True, nullable=False) # e.g., DRV-008
    full_name = db.Column(db.String(100), nullable=False)
    kra_pin = db.Column(db.String(20), unique=True, nullable=False)
    assigned_vehicle_reg = db.Column(db.String(20), nullable=True)
    basic_salary = db.Column(db.Float, default=0.0)
    housing_allowance = db.Column(db.Float, default=0.0)
    is_active = db.Column(db.Boolean, default=True)

    timecards = db.relationship('Timecard', backref='driver', lazy=True)


class Timecard(db.Model):
    __tablename__ = 'timecards'

    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('drivers.id'), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    detention_hours = db.Column(db.Float, default=0.0)
    detention_rate_per_hour = db.Column(db.Float, default=450.0)
    
    # Telematics Safety & Diagnostics
    telematics_hold = db.Column(db.Boolean, default=False)
    active_dtc_code = db.Column(db.String(20), nullable=True) # e.g., P0217 Engine Overheat
    
    # Status: PENDING_APPROVAL, APPROVED, REJECTED, PAYROLL_PROCESSED
    status = db.Column(db.String(30), default='PENDING_APPROVAL')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payroll_record = db.relationship('PayrollRecord', backref='timecard', uselist=False)


class PayrollRecord(db.Model):
    __tablename__ = 'payroll_records'

    id = db.Column(db.Integer, primary_key=True)
    timecard_id = db.Column(db.Integer, db.ForeignKey('timecards.id'), nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Earnings breakdown
    basic_pay = db.Column(db.Float, nullable=False)
    housing_allowance = db.Column(db.Float, nullable=False)
    detention_pay = db.Column(db.Float, nullable=False)
    gross_pay = db.Column(db.Float, nullable=False)
    
    # Statutory Deductions
    nssf_deduction = db.Column(db.Float, nullable=False)
    shif_deduction = db.Column(db.Float, nullable=False)
    housing_levy_deduction = db.Column(db.Float, nullable=False)
    paye_tax = db.Column(db.Float, nullable=False)
    total_deductions = db.Column(db.Float, nullable=False)
    
    net_pay = db.Column(db.Float, nullable=False)

    @staticmethod
    def calculate_statutory(gross_pay):
        """Calculates Kenya statutory deductions (NSSF, SHIF, Affordable Housing Levy, PAYE)."""
        nssf = min(2160.0, gross_pay * 0.06)
        shif = round(gross_pay * 0.0275, 2)
        housing_levy = round(gross_pay * 0.015, 2)
        taxable_pay = gross_pay - nssf

        # PAYE Band Calculations
        if taxable_pay <= 24000:
            paye = taxable_pay * 0.10
        elif taxable_pay <= 32333:
            paye = (24000 * 0.10) + ((taxable_pay - 24000) * 0.25)
        elif taxable_pay <= 500000:
            paye = (24000 * 0.10) + ((32333 - 24000) * 0.25) + ((taxable_pay - 32333) * 0.30)
        else:
            paye = (24000 * 0.10) + ((32333 - 24000) * 0.25) + ((500000 - 32333) * 0.30) + ((taxable_pay - 500000) * 0.35)

        # Apply Personal Relief
        paye = max(0.0, round(paye - 2400.0, 2))
        total_deductions = round(nssf + shif + housing_levy + paye, 2)
        net_pay = round(gross_pay - total_deductions, 2)

        return {
            "nssf": nssf,
            "shif": shif,
            "housing_levy": housing_levy,
            "paye": paye,
            "total_deductions": total_deductions,
            "net_pay": net_pay
        }