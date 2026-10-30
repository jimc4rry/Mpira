# Mpira και Jira: τι λείπει

**Ημερομηνία:** 2026-10-22. **Βάση:** η τεκμηρίωση του Mpira (`docs/MPIRA.md`), έλεγχος του κώδικα, και έρευνα στις σελίδες της Atlassian για το Jira Cloud (εκδόσεις Spring και Summer 2026). Οι πηγές είναι στο τέλος.

**Πώς διαβάζεται:** για κάθε δυνατότητα του Jira, αν το Mpira την έχει, την έχει εν μέρει, ή δεν την έχει. Η στήλη «Αξία» είναι πρόταση για τη δική μας ομάδα (μικρή ομάδα, έως 15 χρήστες, ένα προϊόν, QA αυτοματοποίηση). Η στήλη «Μέγεθος» είναι χοντρική εκτίμηση: S (μέρες), M (1–2 εβδομάδες), L (περισσότερο).

---

## Τι έχει ήδη το Mpira

Projects με κλειδιά, issues (Epic, Story, Task, Bug, Sub-task, Test), προσαρμοσμένα πεδία, σχόλια με @αναφορές, συνημμένα, συνδέσεις, ιστορικό, ειδοποιήσεις μέσα στην εφαρμογή, workflow ανά project με μεταβάσεις, board με ρυθμιζόμενες στήλες και drag & drop, backlog και sprints, burndown και velocity, components, εκδόσεις και ετικέτες, εισαγωγή από CSV, Excel και JSON, wiki με εκδόσεις, test management (steps, plans, executions, coverage, αυτόματη εκτέλεση), REST API με κλειδιά, MCP server για Claude, δίγλωσση διεπαφή.

**Τι έχει το Mpira που το Jira δεν έχει χωρίς πρόσθετα:** test management ενσωματωμένο (στο Jira χρειάζεται το Xray ή παρόμοιο), wiki μέσα στο ίδιο εργαλείο (στο Jira είναι το Confluence, άλλο προϊόν), ουρά αυτόματης εκτέλεσης tests με γραφή αποτελεσμάτων, ελληνική διεπαφή.

---

## 1. Αναζήτηση, φίλτρα, αναφορές

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **JQL:** γλώσσα αναζήτησης (`project = X AND status != Done AND assignee = currentUser()`) | Όχι. Μόνο αναζήτηση κειμένου και φίλτρα board | Υψηλή | M |
| **Αποθηκευμένα φίλτρα**, κοινόχρηστα με την ομάδα | Όχι | Υψηλή | S |
| **Συνδρομές σε φίλτρα:** email με τα αποτελέσματα σε τακτά διαστήματα | Όχι (δεν υπάρχει email) | Μέση | S, μετά το email |
| **Dashboards με gadgets:** ρυθμιζόμενες σελίδες, κάθε gadget = φίλτρο + γράφημα (περίπου 30 εγγενή) | Εν μέρει: μία προσωπική αρχική σελίδα, όχι ρυθμιζόμενη | Μέση | M |
| **Αναφορές:** cumulative flow, control chart, created vs resolved, sprint report, version report, time tracking report | Εν μέρει: burndown, velocity, ολοκληρωμένα και ημιτελή | Μέση | M |
| **Εξαγωγή** αποτελεσμάτων σε CSV ή Excel | Όχι (μόνο εισαγωγή) | Υψηλή | S |
| **Αναζήτηση σε φυσική γλώσσα** που μετατρέπεται σε JQL (AI) | Όχι | Χαμηλή, μετά το JQL | S |

## 2. Προβολές

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **List view:** πίνακας με επεξεργασία μέσα στη γραμμή, ιεραρχία parent/child, αποθηκευμένες προβολές | Εν μέρει: λίστα issues χωρίς inline edit ή αποθήκευση | Υψηλή | M |
| **Timeline:** Gantt με διάρκειες και εξαρτήσεις | Όχι | Υψηλή | M |
| **Calendar:** εργασίες και προθεσμίες σε ημερολόγιο | Όχι | Μέση | S |
| **Summary view:** σελίδα επισκόπησης του project | Εν μέρει: σελίδα project | Χαμηλή | S |
| **Swimlanes στο board** (ανά υπεύθυνο, προτεραιότητα, epic) | Όχι | Μέση | S |
| **Sub-tasks πάνω στις κάρτες** και inline edit στο board | Όχι | Χαμηλή | S |

## 3. Σχεδιασμός

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Plans (Advanced Roadmaps):** σχεδιασμός σε πολλά projects, επίπεδο πάνω από το Epic (initiative), εξαρτήσεις, σενάρια | Όχι | Χαμηλή για μία ομάδα | L |
| **Capacity view:** ποιος έχει χώρο και ποιος είναι υπερφορτωμένος | Όχι | Μέση | M |
| **Releases:** σελίδα εκδόσεων με πρόοδο, version report, αυτόματο release notes | Εν μέρει: εκδόσεις με ημερομηνία και κατάσταση, χωρίς σελίδα προόδου ή release notes | Υψηλή | S |
| **Υπεύθυνος component** και αυτόματη ανάθεση | Όχι | Χαμηλή | S |

## 4. Αυτοματισμοί και ενοποιήσεις

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Automation:** κανόνες με trigger (δημιουργία, αλλαγή πεδίου, μετάβαση, χρονοδιάγραμμα), conditions και actions (μετάβαση, ανάθεση, πεδίο, sub-tasks, σχόλιο, web request) | Όχι | Υψηλή | L |
| **Webhooks:** κλήση εξωτερικού URL σε γεγονότα | Όχι | Υψηλή (CI, Slack) | S |
| **Development panel:** branches, commits, pull requests, builds, deployments, feature flags πάνω στο issue, όταν το κλειδί εμφανίζεται στο commit ή στο branch | Όχι | Υψηλή (χρησιμοποιούμε GitHub) | M |
| **Smart commits:** μετάβαση ή σχόλιο από μήνυμα commit | Όχι | Μέση | S |
| **Slack ή Teams:** ειδοποιήσεις και δημιουργία από chat | Όχι | Μέση | S, μετά τα webhooks |

## 5. Εργασία στα issues

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Time tracking:** αρχική εκτίμηση, υπόλοιπο, worklog, αναφορά | Όχι | Μέση | M |
| **Bulk change:** επεξεργασία, μετάβαση, μετακίνηση, διαγραφή πολλών issues μαζί | Όχι | Υψηλή | M |
| **Clone** και **μετακίνηση issue σε άλλο project** | Όχι | Μέση | S |
| **Αρχειοθέτηση issues** (το Jira το έχει μόνο ανά issue, στα Premium) | Όχι (υπάρχει αρχειοθέτηση project) | Χαμηλή | S |
| **Formula fields:** υπολογιζόμενα πεδία (π.χ. ημέρες ως την προθεσμία) | Όχι | Χαμηλή | M |
| **Πεδίο resolution** (Done, Won't do, Duplicate) | Όχι: το «ολοκληρωμένο» το κρίνει η κατάσταση | Μέση | S |
| **Flag / impediment** στην κάρτα | Όχι | Χαμηλή | S |
| **Πρότυπα issue** και πρότυπα project | Όχι | Χαμηλή | S |
| **Ψήφοι** σε issues | Όχι | Χαμηλή | S |

## 6. Διαχείριση και δικαιώματα

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Permission schemes:** ρυθμιζόμενα δικαιώματα ανά project | Εν μέρει: σταθεροί ρόλοι (Admin, PM, Developer, Tester, Viewer) | Χαμηλή για εμάς | M |
| **Issue security levels:** issues που βλέπει μόνο μια ομάδα | Όχι | Μέση (π.χ. bugs ασφαλείας) | M |
| **Notification schemes:** ποιος ειδοποιείται για ποιο γεγονός | Εν μέρει: σταθεροί κανόνες | Χαμηλή | S |
| **Field configuration και screens:** υποχρεωτικά πεδία ανά τύπο, ποια πεδία φαίνονται σε κάθε οθόνη | Εν μέρει: προσαρμοσμένα πεδία ανά τύπο, όχι υποχρεωτικά ανά μετάβαση | Μέση | M |
| **Workflow conditions, validators, post-functions** (π.χ. «για να κλείσει, πρέπει να έχει υπεύθυνο») | Όχι: μόνο ποια μετάβαση επιτρέπεται | Μέση | M |
| **Audit log:** αλλαγές ρυθμίσεων και συστήματος, με εξαγωγή | Όχι (υπάρχει ιστορικό ανά issue) | Μέση | S |

## 7. Λογαριασμοί, ασφάλεια, πρόσβαση

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Ειδοποιήσεις με email** | Όχι (μόνο μέσα στην εφαρμογή) | Υψηλή | S |
| **Δημιουργία issue με email** | Όχι | Χαμηλή | S |
| **Επαναφορά κωδικού** χωρίς admin | Όχι | Υψηλή | S |
| **SSO (SAML), δύο βημάτων επαλήθευση** | Όχι | Μέση (υψηλή αν μεγαλώσει η ομάδα) | M |
| **Δικαιώματα ανά κλειδί API (scopes) και όριο αιτημάτων** | Εν μέρει: read-only ή πλήρες, χωρίς όριο | Μέση | S |
| **Εφαρμογή για κινητά** | Όχι (η σελίδα δουλεύει σε κινητό browser) | Χαμηλή | L |

## 8. AI

| Δυνατότητα του Jira | Mpira | Αξία | Μέγεθος |
|---|---|---|---|
| **Σύνοψη issue με AI** (τι είναι, πού βρίσκεται, ποιος συμμετέχει, τι ακολουθεί) | Όχι μέσα στην εφαρμογή· γίνεται με Claude μέσω MCP | Μέση | S |
| **Δημιουργία issues από κείμενο** (π.χ. από σημειώσεις ή έγγραφο) | Όχι μέσα στην εφαρμογή· γίνεται με Claude μέσω MCP | Μέση | S |
| **Agents** (Delivery Agent: standup digest, health checks, ενημέρωση stakeholders) | Όχι | Χαμηλή | M |
| **Δημιουργία ολόκληρου project από περιγραφή** | Όχι | Χαμηλή | M |
| **Προτάσεις πεδίων** στη δημιουργία, από το ιστορικό του project | Όχι | Χαμηλή | M |

## 9. Άλλα προϊόντα της Atlassian

Αυτά είναι ξεχωριστά προϊόντα, όχι μέρος του Jira Software. Τα αναφέρω για πληρότητα:
- **Jira Service Management:** πύλη πελατών, ουρές, SLA με κλιμάκωση, τύποι αιτημάτων με δικές τους φόρμες, γνωσιακή βάση. Το Mpira δεν έχει τίποτα από αυτά.
- **Jira Product Discovery:** ιδέες, insights από πελάτες, βαθμολόγηση προτεραιότητας, roadmap Now/Next/Later, μεταφορά σε εργασία.
- **Φόρμες και εγκρίσεις** (business spaces): φόρμα για συλλογή στοιχείων και υπογραφή από εγκριτές.

---

## Πρόταση σειράς για το Mpira

Με κριτήριο την αξία για εμάς και το μέγεθος:

1. **Ειδοποιήσεις με email και επαναφορά κωδικού** (S). Βάση για τις συνδρομές σε φίλτρα και τις ειδοποιήσεις.
2. **Αποθηκευμένα φίλτρα και εξαγωγή σε CSV/Excel** (S). Η εξαγωγή είναι ήδη στη λίστα του Κεφ. 21.
3. **Webhooks** (S). Συνδέουν το Mpira με το CI και το Slack χωρίς ειδικό κώδικα για το καθένα.
4. **Bulk change και list view με inline edit** (M).
5. **Σελίδα εκδόσεων με πρόοδο και release notes** (S).
6. **Development panel με GitHub** (M): branches, commits και PRs πάνω στο issue, μέσω webhook του GitHub και αναζήτησης του κλειδιού.
7. **Απλή γλώσσα αναζήτησης** (M): ένα υποσύνολο του JQL (project, status, type, assignee, label, sprint, version, created/updated) αρκεί για εμάς.
8. **Timeline** (M) και **swimlanes** (S).
9. **Automation** (L): ξεκινώντας από λίγους κανόνες (μετάβαση → ανάθεση, προθεσμία → ειδοποίηση).

Δεν προτείνω για τώρα: Plans, Service Management, Product Discovery, εφαρμογή κινητού, permission schemes. Είναι για μεγάλες ή πολλές ομάδες.

---

## Πηγές

- [What's new in Jira: Summer 2026 release](https://www.atlassian.com/blog/development/jira-summer-release)
- [Jira 2026 Summer Release: New GA features](https://community.atlassian.com/forums/Jira-articles/Introducing-the-Jira-2026-Summer-Release-%EF%B8%8F/ba-p/3268349)
- [Jira 2026 Spring Release](https://community.atlassian.com/forums/Jira-articles/Introducing-the-Jira-2026-Spring-Release/ba-p/3227380/page/2)
- [Atlassian Cloud changes (2026)](https://confluence.atlassian.com/cloud/blog/2026/08/atlassian-cloud-changes-aug-10-to-aug-17-2026)
- [Rovo in Jira: AI features](https://www.atlassian.com/software/jira/ai) και [Create work items with Rovo](https://support.atlassian.com/jira-software-cloud/docs/create-work-items-with-rovo/)
- [Jira automation overview](https://www.atlassian.com/software/jira/guides/automation/overview) και [Jira automation triggers](https://confluence.atlassian.com/automation/triggers-993924804.html)
- [Advanced planning in Jira: Overview of Jira Plans](https://www.atlassian.com/software/jira/guides/advanced-roadmaps/overview)
- [Jira dashboards (titanapps)](https://titanapps.io/blog/jira-dashboards) και [Reporting with Jira's built-in reports and JQL](https://uwaterloo.ca/atlassian/blog/reporting-made-easy-using-jiras-built-reports-and-jql-power)
- [View development information for a work item](https://confluence.atlassian.com/display/JIRASOFTWARECLOUD/Viewing+the+development+information+for+an+issue)
- [Logging time on work items](https://confluence.atlassian.com/jirasoftwarecloud/logging-work-on-issues-902499028.html)
- [Jira project setup basics (schemes)](https://community.atlassian.com/forums/Jira-articles/Jira-Project-Setup-Basics/ba-p/1614740)
- [Bulk archive work items in Jira Cloud](https://support.atlassian.com/jira/kb/bulk-archive-issues-in-jira-cloud/)
- [Creating release notes](https://confluence.atlassian.com/display/JIRA/Creating+Release+Notes)
- [Jira Service Management: service desk](https://www.atlassian.com/software/jira/service-management/features/service-desk)
- [Jira Product Discovery insights overview](https://www.atlassian.com/software/jira/product-discovery/guides/insights/overview)
- [Jira Cloud Hardening Guide (SSO, 2FA)](https://howtoharden.com/guides/jira-cloud/)

**Επιφυλάξεις:** οι ανακοινώσεις της Atlassian δεν περιγράφουν πάντα όλες τις δυνατότητες (η Summer 2026 λέει 15 και περιγράφει 6). Η διαθεσιμότητα εξαρτάται από το πλάνο (Standard, Premium, Enterprise). Για το GitHub στο development panel, μία σελίδα της Atlassian αναφέρει περιορισμό σε Government περιβάλλον, άρα θέλει επιβεβαίωση.
