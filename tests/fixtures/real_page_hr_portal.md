# HR & Payroll Portal

## HR & Payroll Portal

## Summary

The HR & Payroll Portal is an internal application in the organization's As-Is application landscape. It is documented as section 4.19 of the Applications As-Is document [Applications_As-Is_Sample_SJC-Cleansed:39] and as entry "19 HR & Payroll Portal" in the application details [Applications_As-Is_Sample_SJC-Cleansed:539]. The blocks provided carry no detail table for the portal itself. What is known comes from how neighbouring applications refer to it.

## What it is

The portal handles HR and payroll. It took over from the older HR Legacy System, which "was responsible for managing payroll and HR. It was migrated to the HR & Payroll Portal in 2020. However, employees can still access and view the information." [Applications_As-Is_Sample_SJC-Cleansed:824]

## Relationships with other applications

* Evaluate: a service that helps the HR Department create HR evaluation forms. It "has been implemented in the HR & Payroll Portal", so the portal hosts that functionality [Applications_As-Is_Sample_SJC-Cleansed:761].
* Attendance: an internal application that reads and analyzes data from fingerprint machines at different branches. It transfers the results to the HR & Payroll Portal "through API or Excel files" [Applications_As-Is_Sample_SJC-Cleansed:845].
* HR Legacy System: the predecessor, whose payroll and HR functions were migrated into the portal in 2020 [Applications_As-Is_Sample_SJC-Cleansed:824].

## Context

The As-Is document aims to record the current state of applications, their integration and their data exchange paths, and to evaluate their performance and support for the organization's needs [Applications_As-Is_Sample_SJC-Cleansed:81][Applications_As-Is_Sample_SJC-Cleansed:84]. The portal's own owner, hosting, technologies and status are not stated in the available blocks.
