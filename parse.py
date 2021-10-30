import csv
from decimal import Decimal
from enum import Enum
from glob import glob
import json
import logging
import re
import os
from typing import List, Tuple, Optional
import camelot


class Info:
    """
    Info represents all attributes of a monthly statement, except the transactions.
    """

    def __init__(
        self,
        balance_brought_forward: Optional[Decimal] = None,
        balance_carried_forward: Optional[Decimal] = None,
        total_withdrawals: Optional[Decimal] = None,
        total_deposits: Optional[Decimal] = None,
        total_interest_paid_this_year: Optional[Decimal] = None,
        average_balance: Optional[Decimal] = None,
    ) -> None:
        self.balance_brought_forward: Optional[Decimal] = balance_brought_forward
        self.balance_carried_forward: Optional[Decimal] = balance_carried_forward
        self.total_withdrawals: Optional[Decimal] = total_withdrawals
        self.total_deposits: Optional[Decimal] = total_deposits
        self.total_interest_paid_this_year: Optional[
            Decimal
        ] = total_interest_paid_this_year
        self.average_balance: Optional[Decimal] = average_balance


class Transaction:
    """
    Transaction represents a transaction entry in a monthly statement.
    """

    def __init__(
        self,
        transaction_date: str,
        value_date: str,
        description: List[str],
        cheque: str,  # TODO(jonathanwoenardi): Find out what is this.
        withdrawal: Optional[Decimal],
        deposit: Optional[Decimal],
        balance: Optional[Decimal],
    ) -> None:
        self.transaction_date: str = transaction_date
        self.value_date: str = value_date
        self.descriptions: List[str] = description
        self.cheque: str = cheque
        self.withdrawal: Optional[Decimal] = withdrawal
        self.deposit: Optional[Decimal] = deposit
        self.balance: Optional[Decimal] = balance

    def append_description(self, description: str) -> None:
        self.descriptions.append(description)

    def print_optional_decimal(self, value: Optional[Decimal]) -> str:
        if value is None:
            return ""
        else:
            return str(value)

    def csv_row(self):
        return [
            self.transaction_date,
            self.value_date,
            ";".join(
                self.descriptions
            ),  # TODO(jonathanwoenardi): Think of a better representation.
            self.cheque,
            self.print_optional_decimal(self.withdrawal),
            self.print_optional_decimal(self.deposit),
            self.print_optional_decimal(self.balance),
        ]


class SpecialRowDescription(str, Enum):
    """
    SpecialRowDescription are special descriptions for parsing statement info.
    """

    BALANCE_BROUGHT_FORWARD = "BALANCE B/F"
    BALANCE_CARRIED_FORWARD = "BALANCE C/F"
    TOTAL_WITHDRAWALS_DEPOSITS = "Total Withdrawals/Deposits"
    TOTAL_INTEREST_PAID_THIS_YEAR = "Total Interest Paid This Year"
    AVERAGE_BALANCE = "Average Balance"


SPECIAL_ROW_DESCRIPTIONS: List[SpecialRowDescription] = [
    SpecialRowDescription.BALANCE_BROUGHT_FORWARD,
    SpecialRowDescription.BALANCE_CARRIED_FORWARD,
    SpecialRowDescription.TOTAL_WITHDRAWALS_DEPOSITS,
    SpecialRowDescription.TOTAL_INTEREST_PAID_THIS_YEAR,
    SpecialRowDescription.AVERAGE_BALANCE,
]


class Statement:
    """
    Statement represents a monthly statement.
    """

    def __init__(self, info: Info, transactions: List[Transaction]) -> None:
        self.info = info
        self.transactions: List[Transaction] = transactions

    def to_json_default(self, obj):
        # Reference: https://stackoverflow.com/questions/16957275/python-to-json-serialization-fails-on-decimal
        if isinstance(obj, Decimal):
            # TODO(jonathanwoenardi): Research on what should the better way to represent currency in JSON.
            return str(obj)
        return obj.__dict__

    def to_json(self) -> str:
        return json.dumps(self, default=self.to_json_default, indent=4)


class StatementParser:
    """
    StatementParser reads a PDF from a given file path and parse it into a Statement object.
    """

    def __init__(self, pathname: str, filename: str) -> None:
        self._pathname: str = pathname
        self._filename: str = filename
        self.statement: Statement = None
        self.success_count: int = 0
        self.failure_count: int = 0
        self.ignore_count: int = 0

    def parse(self):
        """
        Parse statement from a PDF file.
        """
        # flavor="stream" -> OCBC uses whitespaces instead of lines to separate cells.
        # pages="1-end" -> parse all pages
        tables = camelot.read_pdf(self._pathname, flavor="stream", pages="1-end")
        all_transactions: List[Transaction] = []
        all_special_rows: List[List[str]] = []
        for index in range(len(tables)):
            transactions, special_rows = self.parse_table(tables[index], index)
            all_transactions.extend(transactions)
            all_special_rows.extend(special_rows)
        info = self.parse_special_rows(all_special_rows)
        self.statement = Statement(info, all_transactions)

    def parse_table(
        self,
        table: camelot.core.Table,
        index: int,
    ) -> Tuple[List[Transaction], List[List[str]]]:
        """
        Parse table.
        """
        if len(table.data) == 0:
            return [], []
        data = self.parse_table_header(table.data, index)
        if data is None:
            return [], []
        return self.parse_table_rows(data)

    def parse_table_header(self, data: List[List[str]], index: int) -> List[List[str]]:
        """
        Check whether a table is a transaction table and find the begininning of the table.
        """
        for i in range(len(data)):
            if len(data[i]) == 0:
                return None
            leftmost_word = data[i][0]
            # From general sampling, the `Account No.` row seems to be the most consistent indicator of a transaction table.
            # Many (but not all) transaction tables include the `FRANK ACCOUNT` row just above the `Account No.` row.
            # Some transaction tables include many rows even before the `FRANK ACCOUNT` row.
            # The other non-transaction tables should not include `Account No.` row.
            if leftmost_word.startswith("Account No."):
                # Check the next 2 rows after this row.
                if i + 2 >= len(data):
                    logging.warning("Uncomplete headers")
                    self.failure_count += 1
                    self.save_failure_to_csv(data, index)
                    return None
                next_leftmost_word = data[i + 1][0]
                next2_leftmost_word = data[i + 2][0]
                if (
                    len(data[i]) == 7
                    and next_leftmost_word == "Transaction"
                    and next2_leftmost_word == "Date"
                ):
                    # Normal case
                    self.success_count += 1
                    return data[i + 3 :]
                elif (
                    len(data[i]) == 6
                    and next_leftmost_word == "Transaction\nValue"
                    and next2_leftmost_word == "Date\nDate"
                ):
                    # Exception case 1
                    # On the last page, if there is only special rows and no more transactions entry,
                    # camelot will fail to differentiate the first two columns as two different columns.
                    # This is because the rows are empty and the headers are not separated with enough whitespace.
                    # Exception case 2
                    # Sometimes camelot also fails to differentiate first two columns for unclear reason. TODO(jonathanwoenardi): Investigate.
                    # To mitigate both cases, we will detect the if first and second column are combined and split them.
                    modified_data = []
                    for row in data[i + 3 :]:
                        new_row = []
                        if row[0] == "":
                            new_row = ["", ""]
                        else:
                            new_row = row[0].split("\n")
                            if len(new_row) != 2:
                                logging.warning(
                                    f"Unexpected row in exception case: {row}"
                                )
                                self.failure_count += 1
                                self.save_failure_to_csv(data, index)
                                return None
                        new_row.extend(row[1:])
                        modified_data.append(new_row)
                    return modified_data
                else:
                    # TODO(jonathanwoenardi): There may be more exception cases in the future...
                    logging.warning(
                        f"Unexpected headers after Account No.: {[next_leftmost_word, next2_leftmost_word]}"
                    )
                    self.failure_count += 1
                    self.save_failure_to_csv(data, index)
                    return None
        self.ignore_count += 1
        return None

    def save_failure_to_csv(self, data: List[List[str]], index: int):
        csv_output_pathname = f"failures/{self._filename}-{index}.csv"
        with open(csv_output_pathname, "w") as f:
            writer = csv.writer(f, delimiter=",")
            for row in data:
                modified_row = [elem.replace("\n", "\\n") for elem in row]
                writer.writerow(modified_row)

    def parse_table_rows(
        self, data: List[List[str]]
    ) -> Tuple[List[Transaction], List[List[str]]]:
        """
        Parse all transactions and special rows from a header-stripped transaction table.
        """
        if len(data) == 0:
            return [], []
        if (
            len(data[0]) != 7
        ):  # camelot guarantees that all rows in the table has the same number of columns.
            logging.warning(f"Unexpected statement table column number: {len(data[0])}")
            return [], []
        transactions: List[Transaction] = []
        special_rows: List[List[str]] = []
        current_transaction = None
        for row in data:
            if (
                row[2] in SPECIAL_ROW_DESCRIPTIONS
            ):  # These are special rows that contain specific data of the month.
                special_rows.append(row)
                if row[2] == SpecialRowDescription.AVERAGE_BALANCE:
                    # Cut it short to prevent reading unnecessary rows that is not parsable.
                    return transactions, special_rows
                else:
                    continue
            if row[0] != "":
                if current_transaction is not None:
                    transactions.append(current_transaction)
                try:
                    withdrawal = self.parse_amount(row[4])
                    deposit = self.parse_amount(row[5])
                    balance = self.parse_amount(row[6])
                    current_transaction = Transaction(
                        row[0], row[1], [row[2]], row[3], withdrawal, deposit, balance
                    )
                except Exception as e:
                    logging.warning(f"Parse error: {e}")
            else:
                current_transaction.append_description(row[2])
        if current_transaction is not None:
            transactions.append(current_transaction)
        return transactions, special_rows

    def parse_special_rows(self, rows: List[List[str]]) -> Info:
        """
        Parse statement information from rows with special descriptions.
        """
        info = Info()
        for row in rows:
            try:
                withdrawal = self.parse_amount(row[4])
                deposit = self.parse_amount(row[5])
                balance = self.parse_amount(row[6])
                description = row[2]
                if description == SpecialRowDescription.BALANCE_BROUGHT_FORWARD:
                    info.balance_brought_forward = balance
                elif description == SpecialRowDescription.BALANCE_CARRIED_FORWARD:
                    info.balance_carried_forward = balance
                elif description == SpecialRowDescription.TOTAL_WITHDRAWALS_DEPOSITS:
                    info.total_withdrawals = withdrawal
                    info.total_deposits = deposit
                elif description == SpecialRowDescription.TOTAL_INTEREST_PAID_THIS_YEAR:
                    info.total_interest_paid_this_year = deposit
                elif description == SpecialRowDescription.AVERAGE_BALANCE:
                    info.average_balance = deposit
            except Exception as e:
                logging.warning(f"Parse error: {e}")
        return info

    def parse_amount(self, amount: str) -> Optional[Decimal]:
        """
        Parse currency amount to Decimal.
        """
        if amount == "":
            return None
        return Decimal(re.sub(r"[^\d.]", "", amount))


def main():
    total_success_count = 0
    total_failure_count = 0
    total_ignore_count = 0
    statement_pdf_files = glob("statements/*.pdf")
    for pathname in sorted(statement_pdf_files):
        filename = pathname[len("statements/") : -len(".pdf")]
        s = StatementParser(pathname, filename)
        s.parse()
        total_success_count += s.success_count
        total_failure_count += s.failure_count
        total_ignore_count += s.ignore_count
        # output JSON
        json_output_pathname = f"results/{filename}.json"
        with open(json_output_pathname, "w") as f:
            f.write(s.statement.to_json())
        # output transactions as CSV
        csv_output_pathname = f"results/{filename}.csv"
        with open(csv_output_pathname, "w") as f:
            writer = csv.writer(f, delimiter=",")
            for transaction in s.statement.transactions:
                writer.writerow(transaction.csv_row())
        # finish
        print(
            "parsed: %24s | success: %2d | failure: %2d | ignore: %2d"
            % (filename, s.success_count, s.failure_count, s.ignore_count)
        )
    print(
        "finish | success: %2d | failure: %2d | ignore: %2d"
        % (total_success_count, total_failure_count, total_ignore_count)
    )


if __name__ == "__main__":
    main()
