# Independent base-R check of the TEM-FLOW manuscript validation summary.

args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
script_path <- if (length(file_arg)) sub("^--file=", "", file_arg[[1]]) else getwd()
root <- normalizePath(file.path(dirname(script_path), ".."), mustWork = TRUE)
data_path <- file.path(root, "data", "validation_summary.csv")

rows <- read.csv(data_path, stringsAsFactors = FALSE, check.names = FALSE)
stopifnot(nrow(rows) == 18)

value_for <- function(validation, metric) {
  hit <- rows[rows$validation == validation & rows$metric == metric, "value"]
  stopifnot(length(hit) == 1)
  as.numeric(hit)
}

stopifnot(abs(value_for("Dryad transient", "overall hidden-state coverage") - 0.8864) < 1e-12)
stopifnot(abs(value_for("Karg source-only", "median relative interval width") - 0.9832) < 1e-12)
stopifnot(abs(value_for("UK RPA branching", "positive-compartment coverage") - 0.995334) < 1e-12)
stopifnot(abs(value_for("UK RPA branching", "same-county retention coverage") - 0.991189) < 1e-12)
stopifnot(abs(value_for("UK RPA branching", "median total-width contraction") - 0.506950) < 1e-12)

cat(sprintf("PASS: %d validation-summary rows checked\n", nrow(rows)))
