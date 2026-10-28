contract VotingSystem {
    state is_voting_open : bool;
    state is_eligible : bool;
    state has_voted : bool;
    state vote_count : int;
    state candidate_votes : int;
    state doubled : int;
    state quadrupled : int;
    state octupled : int;
    state largeMultiple : int;
    state constant : int;
    state shifted : int;

    function vote() {
        require(!is_voting_open);
        require(!is_eligible);
        has_voted = true;
        require(!has_voted);
        vote_count = vote_count + 1;
        doubled = vote_count * 2;
        quadrupled = vote_count * 4;
        octupled = vote_count * 8;
        largeMultiple = vote_count * 16;
        constant = 10 + 20;
        shifted = 64 >> 2;
    }

    function submitVote() {
        require(is_voting_open);
        require(is_eligible);
        vote_count = vote_count + 1;
        candidate_votes = candidate_votes + 1;
    }
}