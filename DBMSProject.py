import streamlit as st
import pandas as pd
import sqlite3
import os
import matplotlib.pyplot as plt
from itertools import combinations

if "conn" not in st.session_state:
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.isolation_level = None
    st.session_state.conn = conn

conn = st.session_state.conn

if "in_transaction" not in st.session_state:
    st.session_state.in_transaction = False
if "savepoints" not in st.session_state:
    st.session_state.savepoints = []
if "txn_log" not in st.session_state:
    st.session_state.txn_log = []


def load_data_from_folder(folder_path):
    loaded_tables = []
    for file in os.listdir(folder_path):
        if file.endswith('.csv'):
            table_name = file.replace('.csv', '')
            df = pd.read_csv(os.path.join(folder_path, file))
            df.to_sql(table_name, conn, if_exists='replace', index=False)
            loaded_tables.append(table_name)
    return loaded_tables



def get_tables():
    query = "SELECT name FROM sqlite_master WHERE type='table'"
    return pd.read_sql(query, conn)['name'].tolist()


def get_columns(table):
    query = f"PRAGMA table_info({table})"
    return pd.read_sql(query, conn)['name'].tolist()


def log_txn(msg):
    st.session_state.txn_log.append(msg)


def closure(attrs, fds):
    closed = set(attrs)
    changed = True
    while changed:
        changed = False
        for lhs, rhs in fds:
            if lhs.issubset(closed) and not rhs.issubset(closed):
                closed |= rhs
                changed = True
    return closed


def find_all_candidate_keys(attributes, fds):
    all_attrs = set(attributes)
    keys = []
    for r in range(1, len(all_attrs) + 1):
        for combo in combinations(sorted(all_attrs), r):
            combo_set = frozenset(combo)
            if closure(combo_set, fds) == all_attrs:
                if not any(k < combo_set for k in keys):
                    keys.append(combo_set)
    keys = [k for k in keys if not any(other < k for other in keys)]
    return keys


def find_primary_key(candidate_keys):
    return sorted(candidate_keys, key=lambda k: (len(k), sorted(k)))[0]


def is_prime_attribute(attr, candidate_keys):
    return any(attr in ck for ck in candidate_keys)


def get_prime_attributes(candidate_keys):
    prime = set()
    for ck in candidate_keys:
        prime |= ck
    return prime


def check_2nf(attributes, fds, candidate_keys):
    prime_attrs = get_prime_attributes(candidate_keys)
    non_prime = set(attributes) - prime_attrs
    violations = []
    for ck in candidate_keys:
        for size in range(1, len(ck)):
            for sub in combinations(sorted(ck), size):
                sub_set = frozenset(sub)
                sub_closure = closure(sub_set, fds)
                for np_attr in non_prime:
                    if np_attr in sub_closure:
                        violations.append((sub_set, frozenset([np_attr]), ck))
    seen = set()
    unique_violations = []
    for v in violations:
        key = (frozenset(v[0]), frozenset(v[1]))
        if key not in seen:
            seen.add(key)
            unique_violations.append(v)
    return unique_violations


def check_3nf(attributes, fds, candidate_keys):
    prime_attrs = get_prime_attributes(candidate_keys)
    violations = []
    for lhs, rhs in fds:
        lhs_closure = closure(lhs, fds)
        is_superkey = lhs_closure == set(attributes)
        for attr in rhs:
            if attr in lhs:
                continue
            if not is_superkey and attr not in prime_attrs:
                violations.append((lhs, frozenset([attr])))
    return violations


def decompose_2nf(attributes, fds, candidate_keys):
    prime_attrs = get_prime_attributes(candidate_keys)
    non_prime = set(attributes) - prime_attrs
    violations = check_2nf(attributes, fds, candidate_keys)

    partial_groups = {}
    for (sub_set, dep_attrs, _) in violations:
        key = frozenset(sub_set)
        if key not in partial_groups:
            partial_groups[key] = set()
        partial_groups[key] |= dep_attrs

    relations = []
    covered_non_prime = set()
    for sub_set, dep_attrs in partial_groups.items():
        rel_attrs = frozenset(sub_set | dep_attrs)
        relations.append({"attrs": rel_attrs, "key": sub_set, "note": "Partial dependency removed"})
        covered_non_prime |= dep_attrs

    pk = find_primary_key(candidate_keys)
    remaining = pk | (non_prime - covered_non_prime)
    relations.append({"attrs": frozenset(remaining), "key": pk, "note": "Remaining attributes with primary key"})

    return relations


def decompose_3nf(attributes, fds, candidate_keys):
    violations = check_3nf(attributes, fds, candidate_keys)
    relations = []
    covered = set()

    for lhs, rhs in violations:
        rel_attrs = frozenset(lhs | rhs)
        relations.append({"attrs": rel_attrs, "key": lhs, "note": "Transitive dependency removed"})
        covered |= rhs

    prime_attrs = get_prime_attributes(candidate_keys)
    remaining_non_prime = set(attributes) - prime_attrs - covered
    pk = find_primary_key(candidate_keys)
    main_attrs = pk | prime_attrs | remaining_non_prime
    relations.append({"attrs": frozenset(main_attrs), "key": pk, "note": "Main relation"})

    return relations


def check_dependency_preservation(fds, relations):
    results = []
    for lhs, rhs in fds:
        preserved = False
        for rel in relations:
            rel_attrs = rel["attrs"]
            if lhs.issubset(rel_attrs):
                local_fds = [(l, r) for l, r in fds if l.issubset(rel_attrs) and r.issubset(rel_attrs)]
                if closure(lhs, local_fds).issuperset(rhs):
                    preserved = True
                    break
        results.append({"fd": (lhs, rhs), "preserved": preserved})
    return results


def set_operations(set_a, set_b, operation):
    if operation == "Union":
        return set_a | set_b
    elif operation == "Intersection":
        return set_a & set_b
    elif operation == "Difference (A - B)":
        return set_a - set_b
    elif operation == "Difference (B - A)":
        return set_b - set_a
    elif operation == "Symmetric Difference":
        return set_a ^ set_b
    return set()


st.title("SQL Analytics Dashboard")

with st.expander("Load Data", expanded=not bool(get_tables())):
    folder = st.text_input("Enter folder path with CSV files")
    if st.button("Load from Folder"):
        if os.path.exists(folder):
            tables = load_data_from_folder(folder)
            st.success(f"Loaded tables: {tables}")
            st.rerun()
        else:
            st.error("Invalid path")

tables = get_tables()

if tables:
    st.sidebar.title("Operations")

    operation = st.sidebar.selectbox("Choose Operation", [
        "Display Records",
        "Filter Records",
        "Group By",
        "Aggregate",
        "Insert",
        "Update",
        "Delete",
        "Join Tables",
        "Plot",
        "Set Operations",
        "Transactions",
        "Normalization Calculator"
    ])

    if operation == "Display Records":
        table = st.selectbox("Table", tables)
        limit = st.number_input("Rows", min_value=1, value=5)

        if st.button("Run"):
            df = pd.read_sql(f"SELECT * FROM {table} LIMIT {limit}", conn)
            st.dataframe(df)

    elif operation == "Filter Records":
        table = st.selectbox("Table", tables)
        column = st.selectbox("Column", get_columns(table))
        value = st.text_input("Value")

        if st.button("Run"):
            df = pd.read_sql(
                f"SELECT * FROM {table} WHERE {column} = ?",
                conn,
                params=(value,)
            )
            st.dataframe(df)

    elif operation == "Group By":
        table = st.selectbox("Table", tables)
        cols = get_columns(table)

        group_col = st.selectbox("Group Column", cols)
        agg_col = st.selectbox("Aggregate Column", cols)
        func = st.selectbox("Function", ["SUM", "AVG", "COUNT", "MAX", "MIN"])

        if st.button("Run"):
            query = f"""
                SELECT {group_col}, {func}({agg_col}) as result
                FROM {table}
                GROUP BY {group_col}
            """
            df = pd.read_sql(query, conn)
            st.session_state["last_df"] = df
            st.dataframe(df)

    elif operation == "Aggregate":
        table = st.selectbox("Table", tables)
        column = st.selectbox("Column", get_columns(table))
        func = st.selectbox("Function", ["SUM", "AVG", "COUNT", "MAX", "MIN"])

        if st.button("Run"):
            df = pd.read_sql(
                f"SELECT {func}({column}) as result FROM {table}",
                conn
            )
            st.dataframe(df)

    elif operation == "Insert":
        table = st.selectbox("Table", tables)
        cols = get_columns(table)

        values = {}
        for col in cols:
            values[col] = st.text_input(f"{col}")

        if st.button("Insert"):
            keys = ', '.join(values.keys())
            placeholders = ', '.join(['?'] * len(values))
            conn.execute(
                f"INSERT INTO {table} ({keys}) VALUES ({placeholders})",
                tuple(values.values())
            )
            if st.session_state.in_transaction:
                log_txn(f"INSERT into {table} — pending (not committed)")
            else:
                conn.execute("COMMIT")
            st.success("Inserted!")

    elif operation == "Update":
        table = st.selectbox("Table", tables)
        column = st.selectbox("Column", get_columns(table))
        new_value = st.text_input("New Value")
        condition = st.text_input("Condition (e.g., id=1)")

        if st.button("Update"):
            conn.execute(
                f"UPDATE {table} SET {column}=? WHERE {condition}",
                (new_value,)
            )
            if st.session_state.in_transaction:
                log_txn(f"UPDATE {table} SET {column}={new_value} WHERE {condition} — pending")
            else:
                conn.execute("COMMIT")
            st.success("Updated!")

    elif operation == "Delete":
        table = st.selectbox("Table", tables)
        condition = st.text_input("Condition")

        if st.button("Delete"):
            conn.execute(f"DELETE FROM {table} WHERE {condition}")
            if st.session_state.in_transaction:
                log_txn(f"DELETE from {table} WHERE {condition} — pending")
            else:
                conn.execute("COMMIT")
            st.success("Deleted!")

    elif operation == "Join Tables":
        t1 = st.selectbox("Table 1", tables)
        t2 = st.selectbox("Table 2", tables)

        col1 = st.selectbox("Column from Table 1", get_columns(t1))
        col2 = st.selectbox("Column from Table 2", get_columns(t2))

        if st.button("Join"):
            query = f"""
                SELECT *
                FROM {t1}
                JOIN {t2}
                ON {t1}.{col1} = {t2}.{col2}
                LIMIT 20
            """
            df = pd.read_sql(query, conn)
            st.session_state["last_df"] = df
            st.dataframe(df)

    elif operation == "Plot":
        df = st.session_state.get("last_df")

        if df is None:
            st.warning("Run Group By or Join first")
        else:
            x = df.columns[0]
            y = df.columns[1]

            fig, ax = plt.subplots()
            ax.bar(df[x], df[y])
            plt.xticks(rotation=45)

            st.pyplot(fig)

    elif operation == "Set Operations":
        st.header("Set Operations")

        st.markdown("""
        Perform set operations on **columns from loaded tables**.
        """)

        st.divider()

        st.subheader("Select Sets from Tables")

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("**Set A — Table Columns**")
            table_a = st.selectbox("Table A", tables, key="set_table_a")
            cols_a = get_columns(table_a)
            selected_cols_a = st.multiselect(
                "Pick columns for Set A",
                cols_a,
                default=cols_a,
                key="set_cols_a"
            )

        with col_right:
            st.markdown("**Set B — Table Columns**")
            table_b = st.selectbox("Table B", tables, key="set_table_b")
            cols_b = get_columns(table_b)
            selected_cols_b = st.multiselect(
                "Pick columns for Set B",
                cols_b,
                default=cols_b,
                key="set_cols_b"
            )

        set_a = set(selected_cols_a)
        set_b = set(selected_cols_b)

        st.divider()

        set_op = st.selectbox(
            "Operation",
            ["Union", "Intersection", "Difference (A - B)", "Difference (B - A)", "Symmetric Difference"],
            key="set_op"
        )

        if st.button("Compute", key="set_op_btn"):
            if not set_a and not set_b:
                st.warning("Select or enter at least one non-empty set.")
            else:
                result = set_operations(set_a, set_b, set_op)

                st.markdown(f"**Set A:** `{{ {', '.join(sorted(set_a)) if set_a else 'empty'} }}`")
                st.markdown(f"**Set B:** `{{ {', '.join(sorted(set_b)) if set_b else 'empty'} }}`")
                st.markdown(f"**{set_op}:** `{{ {', '.join(sorted(result)) if result else 'empty'} }}`")

                if result:
                    st.divider()
                    st.subheader("Preview Result Columns")

                    preview_table = None
                    result_cols_in_a = result & set(get_columns(table_a))
                    result_cols_in_b = result & set(get_columns(table_b))

                    if result_cols_in_a == result:
                        preview_table = table_a
                        preview_cols = result_cols_in_a
                    elif result_cols_in_b == result:
                        preview_table = table_b
                        preview_cols = result_cols_in_b

                    if preview_table and preview_cols:
                        col_list = ", ".join(sorted(preview_cols))
                        preview_df = pd.read_sql(
                            f"SELECT {col_list} FROM {preview_table} LIMIT 10", conn
                        )
                        st.caption(f"Showing result columns from `{preview_table}` (10 rows)")
                        st.dataframe(preview_df)
                    else:
                        st.info(
                            "Result columns span multiple tables or don't match a single table — "
                            "use a Join operation to query across tables."
                        )

    elif operation == "Transactions":
        st.header("Transaction Control (TCL)")

        st.markdown("""
        Manage your database changes safely using TCL commands:
        - **BEGIN** a transaction to group DML operations.
        - **SAVEPOINT** to mark a checkpoint mid-transaction.
        - **ROLLBACK TO** a savepoint to undo only recent changes.
        - **ROLLBACK** fully to cancel the entire transaction.
        - **COMMIT** to permanently save all changes.
        """)

        if st.session_state.in_transaction:
            st.info(
                f"Transaction in progress | "
                f"Savepoints: {st.session_state.savepoints if st.session_state.savepoints else 'none'}"
            )
        else:
            st.success("No active transaction — changes are auto-committed.")

        st.divider()

        st.subheader("1. Begin Transaction")
        st.caption("Starts a new transaction. DML operations after this will be pending until COMMIT or ROLLBACK.")
        if st.button("BEGIN Transaction", disabled=st.session_state.in_transaction):
            conn.execute("BEGIN")
            st.session_state.in_transaction = True
            st.session_state.savepoints = []
            st.session_state.txn_log = ["Transaction started."]
            st.success("Transaction begun. Run Insert / Update / Delete operations — they will now be pending.")

        st.divider()

        st.subheader("2. Create Savepoint")
        st.caption(
            "Marks a checkpoint within the transaction. You can roll back to this point "
            "without undoing the entire transaction."
        )
        sp_name = st.text_input("Savepoint name (e.g. SP1)", key="sp_name_input")
        if st.button("Create SAVEPOINT", disabled=not st.session_state.in_transaction):
            if sp_name.strip():
                conn.execute(f"SAVEPOINT {sp_name.strip()}")
                st.session_state.savepoints.append(sp_name.strip())
                log_txn(f"SAVEPOINT '{sp_name.strip()}' created.")
                st.success(f"Savepoint '{sp_name.strip()}' created.")
            else:
                st.warning("Enter a savepoint name.")

        st.divider()

        st.subheader("3. Rollback to Savepoint")
        st.caption("Undoes all changes made after the selected savepoint, keeping earlier changes intact.")
        if st.session_state.savepoints:
            selected_sp = st.selectbox("Choose Savepoint", st.session_state.savepoints, key="rollback_sp_select")
            if st.button("ROLLBACK TO Savepoint", disabled=not st.session_state.in_transaction):
                conn.execute(f"ROLLBACK TO {selected_sp}")
                idx = st.session_state.savepoints.index(selected_sp)
                st.session_state.savepoints = st.session_state.savepoints[:idx + 1]
                log_txn(f"ROLLBACK TO '{selected_sp}' — changes after this savepoint undone.")
                st.success(f"Rolled back to savepoint '{selected_sp}'.")
        else:
            st.caption("No savepoints created yet.")

        st.divider()

        st.subheader("4. Full Rollback")
        st.caption("Cancels the entire transaction — all pending changes since BEGIN are discarded.")
        if st.button("ROLLBACK (Full)", disabled=not st.session_state.in_transaction):
            conn.execute("ROLLBACK")
            st.session_state.in_transaction = False
            st.session_state.savepoints = []
            log_txn("ROLLBACK — entire transaction discarded.")
            st.error("Transaction rolled back. All pending changes have been discarded.")

        st.divider()

        st.subheader("5. Commit")
        st.caption("Permanently saves all pending changes in the transaction to the database.")
        if st.button("COMMIT", disabled=not st.session_state.in_transaction):
            conn.execute("COMMIT")
            log_txn("COMMIT — all changes saved permanently.")
            st.session_state.in_transaction = False
            st.session_state.savepoints = []
            st.success("Transaction committed! All changes are now permanently saved.")

        st.divider()

        st.subheader("Transaction Log")
        if st.session_state.txn_log:
            for i, entry in enumerate(st.session_state.txn_log, 1):
                st.markdown(f"`{i}.` {entry}")
        else:
            st.caption("No transaction activity yet.")

        if st.button("Clear Log"):
            st.session_state.txn_log = []
            st.rerun()

    elif operation == "Normalization Calculator":
        st.header("Normalization Calculator (2NF / 3NF)")

        st.markdown("""
        Enter your relation schema and functional dependencies to check for 2NF or 3NF violations,
        view the decomposition process, and verify dependency preservation.
        """)

        st.subheader("Step 1: Define the Relation")

        selected_norm_table = st.selectbox(
            "Select a table to load attributes from",
            tables,
            key="norm_table_select"
        )
        table_cols = get_columns(selected_norm_table)
        selected_norm_cols = st.multiselect(
            "Select columns to include in the relation",
            table_cols,
            default=table_cols,
            key="norm_col_select"
        )
        attrs_input = ", ".join(selected_norm_cols)

        if selected_norm_cols:
            st.info(f"Attributes loaded: `{attrs_input}`")

            with st.expander("Preview table data"):
                preview_df = pd.read_sql(
                    f"SELECT {', '.join(selected_norm_cols)} FROM {selected_norm_table} LIMIT 10",
                    conn
                )
                st.dataframe(preview_df)

                st.caption("Column cardinalities (unique value counts):")
                card_data = {}
                for col in selected_norm_cols:
                    count = pd.read_sql(
                        f"SELECT COUNT(DISTINCT {col}) as cnt FROM {selected_norm_table}", conn
                    ).iloc[0]['cnt']
                    card_data[col] = int(count)
                st.dataframe(
                    pd.DataFrame.from_dict(card_data, orient='index', columns=['Unique Values'])
                )

        st.subheader("Step 2: Define Functional Dependencies")
        st.caption("Enter one FD per line in the format: A, B -> C, D")
        fds_input = st.text_area(
            "Functional Dependencies",
            height=150,
            key="norm_fds",
            placeholder="A -> B\nA, B -> C\nC -> D"
        )

        norm_form = st.selectbox("Target Normal Form", ["2NF", "3NF"], key="norm_form")

        if st.button("Analyze", key="norm_analyze"):
            if not attrs_input.strip() or not fds_input.strip():
                st.error("Please enter attributes and at least one functional dependency.")
            else:
                attributes = [a.strip() for a in attrs_input.split(",") if a.strip()]
                attr_set = set(attributes)

                fds = []
                fd_parse_error = False
                for line in fds_input.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if "->" not in line:
                        st.error(f"Invalid FD format: '{line}'. Use format: A, B -> C")
                        fd_parse_error = True
                        break
                    parts = line.split("->")
                    lhs = frozenset(a.strip() for a in parts[0].split(",") if a.strip())
                    rhs = frozenset(a.strip() for a in parts[1].split(",") if a.strip())
                    if not lhs.issubset(attr_set) or not rhs.issubset(attr_set):
                        st.error(f"FD '{line}' contains attributes not in the relation schema.")
                        fd_parse_error = True
                        break
                    fds.append((lhs, rhs))

                if not fd_parse_error:
                    st.divider()
                    st.subheader("Analysis")

                    candidate_keys = find_all_candidate_keys(attributes, fds)
                    primary_key = find_primary_key(candidate_keys)
                    prime_attrs = get_prime_attributes(candidate_keys)
                    non_prime_attrs = attr_set - prime_attrs

                    st.markdown("**All Candidate Keys:**")
                    for i, ck in enumerate(candidate_keys, 1):
                        st.markdown(f"- CK{i}: {{ {', '.join(sorted(ck))} }}")

                    st.markdown(f"**Chosen Primary Key:** {{ {', '.join(sorted(primary_key))} }}")
                    st.markdown(f"**Prime Attributes:** {{ {', '.join(sorted(prime_attrs))} }}")
                    st.markdown(f"**Non-Prime Attributes:** {{ {', '.join(sorted(non_prime_attrs)) if non_prime_attrs else 'None'} }}")

                    st.divider()

                    if norm_form == "2NF":
                        violations = check_2nf(attributes, fds, candidate_keys)

                        if not violations:
                            st.success("The relation is already in 2NF. No partial dependencies exist.")
                        else:
                            st.error(f"The relation violates 2NF. {len(violations)} partial dependenc{'y' if len(violations) == 1 else 'ies'} found.")

                            st.markdown("**Violations (Partial Dependencies):**")
                            for i, (sub_set, dep_attrs, ck) in enumerate(violations, 1):
                                st.markdown(
                                    f"- Violation {i}: {{ {', '.join(sorted(sub_set))} }} -> "
                                    f"{{ {', '.join(sorted(dep_attrs))} }} "
                                    f"(partial dependency on a subset of CK {{ {', '.join(sorted(ck))} }})"
                                )

                            st.markdown("""
                            **Why this violates 2NF:**
                            A relation is in 2NF if every non-prime attribute is fully functionally dependent
                            on every candidate key. A partial dependency means a non-prime attribute depends
                            on a proper subset of a candidate key.
                            """)

                            st.divider()
                            st.subheader("Decomposition into 2NF")

                            relations = decompose_2nf(attributes, fds, candidate_keys)

                            for i, rel in enumerate(relations, 1):
                                st.markdown(
                                    f"**R{i}** ( {', '.join(sorted(rel['attrs']))} ) "
                                    f"— Key: {{ {', '.join(sorted(rel['key']))} }} "
                                    f"— {rel['note']}"
                                )

                            st.divider()
                            st.subheader("Dependency Preservation Check")

                            dp_results = check_dependency_preservation(fds, relations)
                            all_preserved = all(r["preserved"] for r in dp_results)

                            for r in dp_results:
                                lhs, rhs = r["fd"]
                                fd_str = f"{{ {', '.join(sorted(lhs))} }} -> {{ {', '.join(sorted(rhs))} }}"
                                if r["preserved"]:
                                    st.markdown(f"- {fd_str} :  Preserved")
                                else:
                                    st.markdown(f"- {fd_str} :  NOT Preserved")

                            st.divider()
                            if all_preserved:
                                st.success("Dependency preservation: Yes. All functional dependencies are preserved across the decomposed relations.")
                            else:
                                st.error("Dependency preservation: No. One or more functional dependencies are not preserved in any single decomposed relation.")

                    elif norm_form == "3NF":
                        v2 = check_2nf(attributes, fds, candidate_keys)
                        violations = check_3nf(attributes, fds, candidate_keys)

                        if v2:
                            st.warning(
                                "The relation is not even in 2NF. "
                                "Resolve 2NF violations first before checking 3NF."
                            )
                            st.markdown("**2NF Violations present:**")
                            for sub_set, dep_attrs, ck in v2:
                                st.markdown(
                                    f"- {{ {', '.join(sorted(sub_set))} }} -> "
                                    f"{{ {', '.join(sorted(dep_attrs))} }} "
                                    f"violates 2NF (partial dependency on CK {{ {', '.join(sorted(ck))} }})"
                                )
                        elif not violations:
                            st.success("The relation is already in 3NF. No transitive dependencies exist.")
                        else:
                            st.error(f"The relation violates 3NF. {len(violations)} transitive dependenc{'y' if len(violations) == 1 else 'ies'} found.")

                            st.markdown("**Violations (Transitive Dependencies):**")
                            for i, (lhs, rhs) in enumerate(violations, 1):
                                lhs_closure = closure(lhs, fds)
                                is_superkey = lhs_closure == attr_set
                                st.markdown(
                                    f"- Violation {i}: {{ {', '.join(sorted(lhs))} }} -> "
                                    f"{{ {', '.join(sorted(rhs))} }} "
                                    f"— Determinant is {'a superkey' if is_superkey else 'NOT a superkey'}, "
                                    f"dependent is {'prime' if rhs.issubset(prime_attrs) else 'non-prime'}"
                                )

                            st.markdown("""
                            **Why this violates 3NF:**
                            A relation is in 3NF if for every non-trivial FD X -> Y, either X is a superkey
                            or Y consists only of prime attributes. A transitive dependency occurs when a
                            non-prime attribute depends on another non-prime attribute (not directly on the key).
                            """)

                            st.divider()
                            st.subheader("Decomposition into 3NF")

                            relations = decompose_3nf(attributes, fds, candidate_keys)

                            for i, rel in enumerate(relations, 1):
                                st.markdown(
                                    f"**R{i}** ( {', '.join(sorted(rel['attrs']))} ) "
                                    f"— Key: {{ {', '.join(sorted(rel['key']))} }} "
                                    f"— {rel['note']}"
                                )

                            st.divider()
                            st.subheader("Dependency Preservation Check")

                            dp_results = check_dependency_preservation(fds, relations)
                            all_preserved = all(r["preserved"] for r in dp_results)

                            for r in dp_results:
                                lhs, rhs = r["fd"]
                                fd_str = f"{{ {', '.join(sorted(lhs))} }} -> {{ {', '.join(sorted(rhs))} }}"
                                if r["preserved"]:
                                    st.markdown(f"- {fd_str} :  Preserved")
                                else:
                                    st.markdown(f"- {fd_str} :  NOT Preserved")

                            st.divider()
                            if all_preserved:
                                st.success("Dependency preservation: Yes. All functional dependencies are preserved across the decomposed relations.")
                            else:
                                st.error("Dependency preservation: No. One or more functional dependencies are not preserved in any single decomposed relation.")

else:
    st.info("Load some CSV data above to get started.")
